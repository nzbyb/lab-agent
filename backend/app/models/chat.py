from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ChatConversation(Base):
    """一次会话。点「新对话」才会断，同一条里的多轮消息挂在它下面。"""

    __tablename__ = "chat_conversation"
    __table_args__ = (
        # 同一用户下 session_key 不重复。这是并发安全网：两个标签页同时首次发消息时，
        # 两边都会查到「没有」然后各自 INSERT，其中一条会撞上这个约束。
        # 撞了由 service 捕获、回滚、重查，不是靠它保证业务正确，是靠它把并发暴露出来。
        UniqueConstraint("user_id", "session_key", name="uq_chat_conv_user_session"),
        {"comment": "AI会话"},
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True, comment="所属用户"
    )
    # 客户端生成的随机标识。**不是主键**，主键仍是 Base 给的整型 id。
    # 用字符串是为了让前端能自己生成、不必先问后端要一个 id（跨域下响应头读不到，
    # 流式接口也没法在响应头里带信息，详见 api/chat.py 的说明）。
    session_key: Mapped[str] = mapped_column(
        String(36), nullable=False, comment="客户端生成的会话标识"
    )
    title: Mapped[str] = mapped_column(
        String(60), nullable=False, default="", comment="标题,取首条提问"
    )


class ChatMessage(Base):
    """会话里的一条消息。"""

    __tablename__ = "chat_message"
    __table_args__ = {"comment": "AI会话消息"}

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("chat_conversation.id"), nullable=False, index=True, comment="所属会话"
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="角色 user/assistant"
    )
    # 用 Text 而不是项目里清一色的 String(n)：正文上限 4000 字，
    # 但那是业务上限、将来可能调；Text 不必跟着改列宽（MySQL TEXT 64KB）。
    #
    # 允许空串：只有工具调用、模型没吐正文的那一轮也要能存下来（需求要求存执行过程），
    # 所以不能在这里卡 min_length，判断交给 service。
    content: Mapped[str] = mapped_column(
        Text, nullable=False, default="", comment="正文"
    )
    # 工具调用时间线，json.dumps 后存字符串。存 JSON 文本而不是拆成子表：
    # 它只跟着这条消息整存整取，从不单独查询，拆表只会多一次 join。
    steps: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="工具调用时间线 JSON"
    )
