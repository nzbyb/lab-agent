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

    @model_validator(mode="after")
    def _cap_total_content(self):
        total = sum(len(message.content) for message in self.messages)
        if total > _MAX_TOTAL_CONTENT:
            raise ValueError(f"单次请求的对话总长度不能超过 {_MAX_TOTAL_CONTENT} 字")
        return self
