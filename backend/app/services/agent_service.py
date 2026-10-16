import json
import traceback
from datetime import datetime
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.common.exceptions import BusinessException
from app.schemas.ai import ChatRequest
from app.services import agent_tools, lab_service
from app.config import settings

SYSTEM_PROMPT = """你是智能实验室预约系统的 Agent，你的名字是小田，当用户提到你的名字时，要有回应。回答要丰富一些，多使用表情和颜文字，营造活人感。
你可以：
1. 使用 search_lab_docs 查询实验室的规则、安全、开放时间等问题
2. 使用 list_labs / list_lab_equipments 查询真实的实验室和设备
3. 再用户进行了预约确认后，使用 create_lab_reservation 来进行真实的预约落库
4. 使用 get_today 来进行日期的换算
5. 使用 list_lab_free_slots 查询某天某个实验室或者设备的空闲时段

【当前时间】{now}

【"开放"是什么意思】
"开放"= 此刻正好落在这间实验室今天的开放时段里。list_labs 返回的 open_now 就是这个判断的结论，直接用它，不要按名字或者印象猜。
下面三件事别混在一起说：
- enabled=false：管理员把这间实验室停用了，跟几点钟没关系。
- today_hours=null：这间实验室**今天**不开门（周末不开放的实验室，周末问就是这种）。
- open_now=false：今天开门，但此刻还不到点，或者已经过了。
每间实验室周中和周末是两个时段（返回体里的 weekday_hours 和 weekend_hours），问"周末能约吗""几点关门"时要想到这个区别。

【最要紧的一条】
"现在开着吗""有几间开着""现在还能约吗"这类问题的答案会随时间变。**每一轮都必须重新调用工具去查，不许沿用之前对话里说过的结论。**
如果这一轮查到的和之前说过的对不上，以这一轮查到的为准，并且直接告诉用户你之前说错了、正确的是什么，不要含糊带过、也不要两边都圆。

在提交预约之前必须向用户复述：实验室ID与名称（或设备ID和名称）、日期、开始时间、结束时间。并得到用户确认再进行实际操作。
用户没说【确认预约】【就这样预约】等确定性回复之前，不要调用 create_lab_reservation。
工作流的确认环节里如果缺少了 lab_id，请先 list_labs 查到了 lab_id 再创建，不要瞎写。
工作流的确认环节里如果缺少了 equipment_id，请先 list_lab_equipments 查到了 equipment_id 再创建，不要瞎写。
用户问"某天能不能约""什么时候有空"时，先用 get_today 换算日期，再 list_lab_free_slots 查空闲时段，不要凭空猜测。
查询空闲时段前，先用 list_labs / list_lab_equipments 拿到真实的 lab_id、equipment_id，不要瞎写。

预约成功后状态是待审核，必须管理员确认后实验室（或设备）才能使用。
不要瞎编数据库里没有的实验室或者设备信息。
如果是问开放时间或者实验室规则，优先调用 search_lab_docs，不要凭空回复。
"""

TOOL_LABELS = {
    "search_lab_docs": "检索实验室知识库",
    "list_labs": "查询实验室",
    "list_lab_equipments": "查询实验室设备",
    "list_lab_free_slots": "查询空闲时段",
    "create_lab_reservation": "创建预约单",
    "get_today": "获取当前日期时间",
}


def build_system_prompt(now: datetime | None = None) -> str:
    """拼出这一轮的系统提示词。

    当前时间必须每轮现算、当场拼进去：模型自己不知道"现在几点、今天星期几"，
    而"现在哪些实验室开着"恰好两样都依赖。之前提示词里没这句话，
    模型就只能拿对话里的旧结论硬答——用户晚上 21:39 问到"8 间实验室开放"，
    这是成因之一。
    """
    return SYSTEM_PROMPT.format(now=lab_service.describe_moment(now or datetime.now()))



# 真正送进模型的对话条数上限。前端传上来的是整段历史，
# 不截断的话上下文会随对话无限膨胀，既慢又贵。
_MAX_HISTORY_MESSAGES = 20


def _build_history(data: ChatRequest) -> list:
    history = []
    for message in data.messages:
        if message.role == "user" and message.content.strip():
            history.append(HumanMessage(content=message.content.strip()))
        elif message.role == "assistant" and message.content.strip():
            history.append(AIMessage(content=message.content.strip()))
    if not history:
        raise BusinessException(message="请输入您的对话内容")
    # 截断放在过滤之后：空消息已经先被丢掉了，20 条指的是真正进模型的那个数。
    # 只保留最近的——越靠后的轮次对当前这问越相关。
    return history[-_MAX_HISTORY_MESSAGES:]


def _tool_output_text(output: Any) -> str:
    if isinstance(output, ToolMessage):
        output = output.content
    return output if isinstance(output, str) else str(output)


# 摘要最多这么长，超了截断。纯粹是防意外：知识库原文、几十间实验室的名字
# 都可能在一条里，界面上那行不该被它撑爆。
_SUMMARY_MAX = 120

# 列表类摘要最多列几个名字，剩下的用省略号带过
_SUMMARY_NAMES = 4


def _clip(text: str) -> str:
    text = (text or "").strip()
    return text if len(text) <= _SUMMARY_MAX else text[: _SUMMARY_MAX - 1] + "…"


def _name_list(rows: Any) -> str:
    names = [
        str(row.get("name") or "").strip()
        for row in (rows or [])
        if isinstance(row, dict)
    ]
    names = [name for name in names if name]
    if not names:
        return ""
    head = "、".join(names[:_SUMMARY_NAMES])
    return head + "…" if len(names) > _SUMMARY_NAMES else head


def _slot_list(slots: Any) -> str:
    return "、".join(
        f"{item.get('start_time')}-{item.get('end_time')}"
        for item in (slots or [])
        if isinstance(item, dict)
    )


def _tool_summary(name: str, output: Any) -> str:
    """把工具的返回值说成**一句人话**，给界面上的「执行过程」用。

    工具的返回值是写给模型看的紧凑 JSON（键名全是英文），原样摆到界面上，
    用户看到的是一串花括号，像是把一个调试面板漏了出来。所以同一份数据在这里
    按工具名翻一遍，前端只显示这句话——**原始 JSON 不再往前端送**。

    认不出来的工具（以后新加的、还没在这儿登记）返回空串，界面上只显示工具名，
    不显示任何原始数据：宁可少一行，也别把 JSON 漏出去。
    """
    text = _tool_output_text(output).strip()

    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        # search_lab_docs 回的是知识库原文，不是 JSON。取头一行当摘要。
        first = next((line.strip(" #*-") for line in text.splitlines() if line.strip()), "")
        return _clip(first)

    if not isinstance(data, dict):
        return ""
    if data.get("ok") is False:
        return _clip(f"失败：{data.get('error') or '操作失败'}")

    if name == "get_today":
        return f"今天是 {data.get('date')} {data.get('weekday')}，现在 {data.get('time')}"

    if name == "list_labs":
        total = data.get("total") or 0
        if not total:
            return "没有匹配的实验室"
        return _clip(f"共 {total} 间：{_name_list(data.get('labs'))}")

    if name == "list_lab_equipments":
        total = data.get("total") or 0
        if not total:
            return "这间实验室没有匹配的设备"
        return _clip(f"共 {total} 台：{_name_list(data.get('equipments'))}")

    if name == "list_lab_free_slots":
        who = data.get("equipment_name") or data.get("lab_name") or "实验室"
        date = data.get("date") or ""
        slots = data.get("free_slots") or []
        if not slots:
            return f"{who} {date} 已约满，没有空闲时段"
        return _clip(f"{who} {date} 空闲 {len(slots)} 段：{_slot_list(slots)}")

    if name == "create_lab_reservation":
        return (
            f"已提交预约：{data.get('date')} "
            f"{data.get('start_time')}-{data.get('end_time')}，等待管理员审核"
        )

    return ""


def _chunk_text(chunk: Any):
    if chunk is None:
        return ""
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(part.get("text") or "")
        return "".join(parts)
    return str(content) if content is not None else ""


async def stream_agent(user_id: int, data: ChatRequest):
    try:
        history = _build_history(data)
        agent = build_agent(user_id)
        inputs = {"messages": [SystemMessage(content=build_system_prompt()), *history]}

        yield {"type": "status", "message": "正在思考..."}

        async for event in agent.astream_events(
            inputs, version="v2", config={"recursion_limit": 10}
        ):
            kind = event.get("event")
            if kind == "on_chat_model_start":
                # 每次模型调用开始时，把状态刷回「正在思考...」。
                #
                # 不加这条，工具跑完之后状态会一直停在上一条「XX完成」——而模型
                # 这时候正在写答案，实测这一段能到 20 秒以上。界面上写着「已完成」
                # 却半天不动，比什么都不显示更容易被当成卡死。
                #
                # 前端只在「没有工具正在跑」时才显示这条状态，所以工具执行期间
                # 不会和时间线里那句「正在查询...」重复。
                metadata = event.get("metadata") or {}
                if metadata.get("langgraph_node") in (None, "agent"):
                    yield {"type": "status", "message": "正在思考..."}
            elif kind == "on_tool_start":
                name = event.get("name") or ""
                yield {
                    "type": "tool_start",
                    "name": name,
                    "label": TOOL_LABELS.get(name, name),
                }
            elif kind == "on_tool_end":
                name = event.get("name") or ""
                yield {
                    "type": "tool_end",
                    "name": name,
                    "label": TOOL_LABELS.get(name, name),
                    # 一句中文结果，界面上「执行过程」那一步显示的就是它。
                    # 工具的原始 JSON 只给模型看，不再往前端送（见 _tool_summary）。
                    "summary": _tool_summary(
                        name, (event.get("data") or {}).get("output")
                    ),
                }
            elif kind == "on_chat_model_stream":
                metadata = event.get("metadata") or {}
                if metadata.get("langgraph_node") not in (None, "agent"):
                    continue
                text = _chunk_text((event.get("data") or {}).get("chunk"))
                yield {
                    "type": "token",
                    "content": text,
                }
        yield {"type": "done"}

    except BusinessException as e:
        yield {"type": "error", "message": e.message}
    except Exception as e:
        traceback.print_exc()
        yield {"type": "error", "message": "大模型调用失败，请稍后重试"}


def build_agent(user_id: int):
    # 只传 id，不传会话：工具各自开会话，见 agent_tools.build_tools 的说明。
    tools = agent_tools.build_tools(user_id)
    llm = ChatOpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        model=settings.LLM_MODEL,
        temperature=0,
        streaming=True,
        # 封住单次回复的长度。不设的话模型可以一直往外吐，请求既慢又贵。
        #
        # 必须走 extra_body，不能直接写 max_tokens=：langchain-openai 把
        # max_tokens 改名成了 max_completion_tokens，构造参数和 model_kwargs
        # 都会在发请求前被改名。DeepSeek 只认 max_tokens，收到
        # max_completion_tokens 不报错、直接忽略——上限等于没设。
        # extra_body 是在改名之后合并进 HTTP 请求体的，能原样送到。
        #
        # 这段的前提是 LLM_BASE_URL 指的是 DeepSeek 兼容接口。换成标准
        # OpenAI 的模型时，把 extra_body 换回 max_tokens= 即可。
        extra_body={"max_tokens": 1024},
        # 超时和重试次数必须显式给。这两项"不设"的后果不一样，而且都不好：
        #
        # timeout 不设 ≠ 走 SDK 那 600 秒的默认值。langchain 的 request_timeout
        # 默认就是 None，它会把这个 None 原样递给 openai 客户端；客户端一看
        # "调用方明确给了值"，就跳过了自己的 DEFAULT_TIMEOUT 兜底。实测：
        #     ChatOpenAI(...).root_async_client.timeout  ->  None
        # 也就是说**根本没有超时**——连接真挂住的话它会一直等下去，不报错也不返回。
        # 这里写死 30 秒，等于把这个洞补上。
        #
        # max_retries 不设则相反：langchain 自己默认 None、不转发，于是 SDK 那层
        # 的 DEFAULT_MAX_RETRIES = 2 生效。实测 root_async_client.max_retries -> 2。
        #
        # 实测这个网关会偶发「卡 20 秒左右，然后一个字节都不回就把连接掐掉」，
        # 底层报的是 RemoteProtocolError: Server disconnected without sending
        # a response。用默认值时，一次 20 秒的故障会被 2 次重试放大成等 80 多秒
        # 才弹「大模型调用失败」；用户感知就是「小田反应极慢，最后还报错」。
        #
        # 30 秒管的是「多久收不到任何字节就放弃」：正常首字节只要 0.4~0.6 秒，
        # 实测最慢的一次成功响应是 24 秒，所以 30 秒不会误杀正常回答。
        # 留 1 次重试是为了兜偶发断流；再往上加只会让失败时等得更久。
        # （注：timeout 是 request_timeout 的别名，两种写法等价。）
        #
        # 另：langchain 在流式这条路上还自带一层 stream_chunk_timeout（实测默认
        # 120.0），管的是"相邻两个分片之间隔多久算断"。那是另一层护栏，不是请求
        # 超时——别把它当成"原来其实有兜底"的依据。
        timeout=30.0,
        max_retries=1,
    ).bind_tools(tools)

    async def agent_node(state: MessagesState):
        response = await llm.ainvoke(state["messages"])
        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")  # ← 补上，见下面第 1 条
    return graph.compile()


# def run_agent(db: Session, current_user: User, data: ChatRequest):
#     if not data.messages:
#         raise BusinessException(message="对话内容为空")
#     history = []
#     for message in data.messages:
#         if message.role == "user" and message.content.strip():
#             history.append(HumanMessage(content=message.content.strip()))
#         elif message.role == "assistant" and message.content.strip():
#             history.append(AIMessage(content=message.content.strip()))
#     if not history:
#         raise BusinessException(message="请输入您要对话的内容")

#     agent = build_agent(db, current_user)
#     try:
#         result = agent.invoke(
#             {"messages": [SystemMessage(content=SYSTEM_PROMPT), *history]},
#             config={"recursion_limit": 10},
#         )
#     except BusinessException:
#         raise
#     except Exception:
#         raise BusinessException(message="大模型调用失败，请稍后重试")

#     messages = result.get("messages") or []
#     if not messages:
#         raise BusinessException(message="大模型没有任何的返回内容")
#     for message in reversed(messages):
#         if isinstance(message, AIMessage) and message.content.strip():
#             content = message.content.strip()
#             if isinstance(content, list):
#                 content = "".join(
#                     part.get("text", "") if isinstance(part, dict) else str(part)
#                     for part in content
#                 )
#             if str(content).strip():
#                 return str(content).strip()
