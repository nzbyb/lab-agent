from typing import Literal

from pydantic import BaseModel, Field, model_validator

# 单条消息的长度上界，按角色分档。
#
# 用户那侧要跟输入框的 maxlength 对齐，是手打内容的真实上限；
# 助手那侧是我们自己回显的对话历史，给宽一点——它比用户输入长是正常的
# （markdown 列表、表格），卡太死会让整段对话在某一轮突然发不出去。
# 但也不能不设：请求体是从浏览器发过来的，客户端想塞多长就多长。
_MAX_USER_CONTENT = 2000
_MAX_ASSISTANT_CONTENT = 4000

# 整个请求体所有消息加起来的字符数上界。
# 条数上限是 100，只卡条数的话 100 × 4000 还是能拼出一个 1MB 级的请求体。
_MAX_TOTAL_CONTENT = 100_000


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)

    @model_validator(mode="after")
    def _cap_content_length(self):
        limit = _MAX_USER_CONTENT if self.role == "user" else _MAX_ASSISTANT_CONTENT
        if len(self.content) > limit:
            raise ValueError(f"单条消息不能超过 {limit} 字")
        return self


class ChatRequest(BaseModel):
    # 条数上限挡的是滥用。真正送进模型的上下文由 agent_service 截断到最近
    # 20 条——前端传的是整段历史，不能因为聊到第 21 句就整个发不出去。
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)

    # 客户端生成的会话标识，用来把这轮对话挂到哪条历史会话上。
    #
    # 名字**刻意不叫 conversation_id**：它对应的是 chat_conversation.session_key
    # 那个字符串，不是数据库的整型主键。两个都叫 id 一定会有人用混。
    #
    # 长度和字符集必须卡住：请求体是浏览器发过来的，不卡的话一个超长字符串会
    # 直接撞上 String(36) 的列宽，在 MySQL 严格模式下变成 500 而不是 422。
    # 允许 None（老客户端不带这个字段时，这轮就单纯不落库，不影响对话本身）。
    session_key: str | None = Field(
        default=None, min_length=8, max_length=36, pattern=r"^[0-9a-zA-Z_-]+$"
    )

    @model_validator(mode="after")
    def _cap_total_content(self):
        total = sum(len(message.content) for message in self.messages)
        if total > _MAX_TOTAL_CONTENT:
            raise ValueError(f"单次请求的对话总长度不能超过 {_MAX_TOTAL_CONTENT} 字")
        return self
