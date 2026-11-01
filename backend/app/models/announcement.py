from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Announcement(Base):
    """站内公告。

    publisher_id 允许为空（设置 SET NULL）：管理员账号被删了，公告本身不该跟着消失，
    标题下面留一个发布人名称快照就够看了。
    status 分"草稿/已发布"而不是直接删了重发——公告改个错别字很常见，
    编辑中的版本不该提前被学生看到。
    """

    __tablename__ = "announcements"
    __table_args__ = (
        # 列表固定是"已发布 + 置顶优先 + 时间倒序"
        Index("ix_announcements_status_pinned", "status", "pinned", "id"),
        {"comment": "公告"},
    )

    title: Mapped[str] = mapped_column(String(100), nullable=False, comment="标题")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="正文")
    pinned: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False, comment="是否置顶"
    )
    status: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
        comment="状态: 0-草稿, 1-已发布",
    )
    publisher_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, comment="发布人ID"
    )
    publisher_name: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="发布人名称快照"
    )
