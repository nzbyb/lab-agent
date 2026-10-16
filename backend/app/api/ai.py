import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from app.common.response import Response

from app.dependencies.auth import get_current_user
from app.limiter import limiter
from app.models.user import User
from app.schemas.ai import ChatMessage, ChatRequest
from app.services import agent_service, chat_service

router = APIRouter(prefix="/ai", tags=["AI相关的API"])


# @router.post("/chat")
# def chat(
#     data: ChatRequest,
#     current_user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     content = agent_service.run_agent(db, current_user, data)
#     return Response.success(data=ChatMessage(role="assistant", content=content))


def _finish_step(steps: list, event: dict) -> None:
    """把 tool_end 配到它对应的那条 tool_start 上。

    语义与前端 AIChat.vue 的 findRunningStep 一致，从后往前找「还在跑、且工具名
    相同」的那条——同一轮里同一个工具可能被调用多次（反复查不同日期的空闲时段），
    只按名字找会配错；工具是串行执行的，所以「最后一个还在跑的」就是它。
    配不上（正常不该发生）就补一条已完成的，宁可多记一步，也不要让过程少一段。
    """
    name = event.get("name") or ""
    for step in reversed(steps):
        if step["state"] == "running" and (not name or step["name"] == name):
            step["state"] = "done"
            step["summary"] = event.get("summary") or ""
            return
    steps.append(
        {
            "name": name,
            "label": event.get("label") or name,
            "state": "done",
            "summary": event.get("summary") or "",
        }
    )


async def _event_stream(user_id: int, data: ChatRequest):
    """把 Agent 的事件流转成 SSE，同时把这轮对话落进历史。

    提成模块级函数（不放路由体里内联）是为了测试能直接驱动它——包括拿到第一个
    事件后立刻 aclose() 来模拟「用户关掉网页」，那是本功能最容易出错的一条路径。
    """
    # 只收一个整数 user_id，不收请求作用域的会话或用户对象——生成器真正开始跑时
    # 它们已经被回收了。工具各自开自己的会话（见 agent_tools.build_tools），落库走
    # chat_service 自己的会话，所以这里没有东西需要往下传。
    session_key = data.session_key

    # 阶段 A：用户提问先落库。
    # 放在**吐字之前**而不是整段结束之后，是因为它必须在一个「一定会执行到」的位置：
    # 用户中途关网页时，后面循环之后的代码根本跑不到。
    # 这个方法自己吞异常，写失败也只是这轮不落库，不会让用户连话都问不出去。
    conversation_id = chat_service.record_user_turn(user_id, data)

    text_parts: list[str] = []
    steps: list[dict] = []

    try:
        async for event in agent_service.stream_agent(user_id, data):
            etype = event.get("type")
            if etype == "token":
                text_parts.append(event.get("content") or "")
            elif etype == "tool_start":
                steps.append(
                    {
                        "name": event.get("name") or "",
                        "label": event.get("label") or event.get("name") or "",
                        "state": "running",
                        "summary": "",
                    }
                )
            elif etype == "tool_end":
                _finish_step(steps, event)
            elif etype == "done" and conversation_id is not None:
                # 前端发上来的是字符串的 session_key，但列表/消息接口认整型 id。
                # 在这里把 id 一起送回去，前端一次就能把两个标识都记下，
                # 不用为了拿 id 再查一次列表。
                # （不能用响应头回传：这个项目的跨域配置没开放自定义响应头，读不到。）
                event = {**event, "conversation_id": conversation_id}
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    finally:
        # 阶段 B：助手回复落库。
        #
        # 放在 finally 里是**这个功能的要害**：用户中途关网页时，这段生成器会被
        # 取消（抛 CancelledError，它不属于 Exception，现有那个兜底 except 拦不住），
        # 循环之后的普通代码一律不执行——只有 finally 会执行。
        # 不这么写，表现就是「偶尔丢对话」，而且只在断线时发生，极难查。
        #
        # 两条硬约束由此而来：全程同步、不许 await（同步 SQLAlchemy 正好合适）；
        # 绝不许往外抛（在取消清理中抛新异常会顶掉取消信号，引发 anyio 告警）。
        # 方法内部自己 try/except，这里不再包一层。
        #
        # error 事件的文案**不落库**：那是我方生成的提示（"大模型调用失败，请稍后重试"），
        # 落进去下次回看、回灌给模型时，就变成了助手说过的话。
        # 只存真实吐出来的 token 和工具过程。
        chat_service.record_assistant_turn(
            user_id, session_key, "".join(text_parts), steps
        )


# 每次对话都要真金白银调一次大模型，而且是流式长连接，单次能占住很久。
# 不限流的话一个脚本就能把额度刷干、把并发连接占满。
# 注意：slowapi 要求在签名里有个名字正好是 request 的参数，别改名。
@router.post("/chat/stream")
@limiter.limit("20/minute")
async def chat_stream(
    request: Request,
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    # 在路由体里就把 id 取出来（这时依赖的会话还活着），生成器只认这个整数。
    # 不再注入 get_db：这个接口自己一个查询都不做，开了也是白占一条连接。
    return StreamingResponse(
        _event_stream(current_user.id, data),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
