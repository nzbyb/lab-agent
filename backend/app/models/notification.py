from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Notification(Base):
    """站内消息。

    目前只由预约状态变化产生（审核通过 / 驳回 / 管理员强制取消 / 超时自动取消），
    所以 type 是这几种固定值。以后要加别的消息类型时，直接往字符串里加，不用改表。

    reservation_id 刻意**不建外键**：消息是历史记录，预约将来如果被删掉，
    消息里那句话仍然成立（用户看到的是"你约的 3 楼 201 被取消了"）。
    建了外键反而会让删除预约被消息挡住，或者级联把消息一起清掉。
    """

    __tablename__ = "notifications"
    __table_args__ = (
        # 页面只查"我的、未读的"，计数也只查这两个条件，合成一个索引就够。
        Index("ix_notifications_user_read", "user_id", "is_read"),
        {"comment": "站内消息"},
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="接收人",
    )
    type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="类型: audit_approved/audit_rejected/force_canceled/auto_canceled",
    )
    title: Mapped[str] = mapped_column(String(100), nullable=False, comment="标题")
    content: Mapped[str] = mapped_column(String(500), nullable=False, comment="正文")
    reservation_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="关联预约ID,仅用于跳转"
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False, comment="是否已读"
    )
    read_time: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="阅读时间"
    )
