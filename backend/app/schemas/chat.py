from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ChatConversationResponse(BaseModel):
    """历史列表里的一条会话。"""

    id: int
    session_key: str
    title: str
    update_time: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatMessageResponse(BaseModel):
    """一条消息。

    这里同时给出 id 和 session_key 之外的两个标识，前端切会话时两个都要用：
    列表/消息接口认整型的 id，流式接口认字符串的 session_key。
    流结束时后端会把这条会话的 id 一并回传，前端一次就能把两个都记下。
    """

    id: int
    role: str
    # 正文可能是空串（只有工具调用、模型没吐字的那一轮），所以不设 min_length
    content: str
    # service 里 json.loads 过再塞进来，给前端的是结构化数组而不是字符串
    steps: list | None = None
    create_time: datetime
