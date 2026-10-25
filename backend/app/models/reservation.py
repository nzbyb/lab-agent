from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.equipment import Equipment
from app.models.lab import Lab
from app.models.user import User


class Reservation(Base):
    __tablename__ = "reservation"
    __table_args__ = {"comment": "预约信息"}

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), comment="预约人", nullable=False
    )
    lab_id: Mapped[int] = mapped_column(
        ForeignKey("labs.id"), comment="实验室", nullable=False
    )
    equipment_id: Mapped[int] = mapped_column(
        ForeignKey("equipments.id"), comment="设备,空表示预约实验室", nullable=True
    )
    date: Mapped[str] = mapped_column(String(20), comment="预约日期", nullable=False)
    start_time: Mapped[str] = mapped_column(
        String(20), comment="开始时间", nullable=False
    )
    end_time: Mapped[str] = mapped_column(
        String(20), comment="结束时间", nullable=False
    )
    remark: Mapped[str] = mapped_column(String(255), comment="备注", nullable=True)
    status: Mapped[int] = mapped_column(
        comment="预约状态 0待审核, 1已通过, 2已拒绝, 3已取消", default=0
    )
    # 下面三列是「我的预约」时间线和取消原因用的。
    #
    # 不拿 update_time 代替：那一列任何一次写入都会变（比如以后改备注），
    # 时间线会跟着漂。审核时间和取消时间各自记一次，才说得清"什么时候发生的"。
    audit_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="审核时间"
    )
    cancel_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="取消时间"
    )
    cancel_reason: Mapped[str | None] = mapped_column(
        String(255), comment="取消原因"
    )
    user: Mapped[User] = relationship()
    lab: Mapped[Lab] = relationship()
    equipment: Mapped[Equipment] = relationship()
