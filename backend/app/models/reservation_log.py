from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ReservationLog(Base):
    """一条预约经历过什么：谁建的单、谁审的、谁取消的、系统什么时候清掉的。

    这是「详情页时间线」的数据源，跟 audit_logs 有重叠但视角不同：
    audit_logs 回答"某个管理员做了什么"（全局、按人查），
    这张表回答"这条预约发生了什么"（按单查，用户自己也看得到）。

    operator_id 允许为空、并且 ondelete=SET NULL：管理员账号被删掉之后，
    历史记录仍然要留着（operator_name 是当时的快照），不能因为人没了就断链。
    """

    __tablename__ = "reservation_logs"
    __table_args__ = (
        Index("ix_reservation_logs_reservation", "reservation_id", "id"),
        {"comment": "预约变更记录"},
    )

    reservation_id: Mapped[int] = mapped_column(
        ForeignKey("reservation.id", ondelete="CASCADE"),
        nullable=False,
        comment="预约ID",
    )
    action: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="动作: create/approve/reject/cancel/force_cancel/auto_cancel",
    )
    from_status: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="变更前状态, 新建时为空"
    )
    to_status: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="变更后状态"
    )
    operator_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="操作人ID, 系统自动取消时为空",
    )
    operator_name: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="操作人名称快照"
    )
    reason: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="原因, 如强制取消的理由"
    )
