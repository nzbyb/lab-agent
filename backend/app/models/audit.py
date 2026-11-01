from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AuditLog(Base):
    """操作日志与登录日志。

    登录失败也要记，所以这一列 **user_id 允许为空**：账号根本不存在时
    没有外键可指，只能把"对方试的那个账号"存进 username 快照。

    username 同样不是冗余：用户改过账号名之后，日志要还原的是
    "当时是谁"，外键指过去只能看到现在的名字。

    action 统一用 `域.动作` 的写法（login.success / lab.update /
    reservation.force_cancel），前端按前缀筛分类，不用再维护一张枚举表。
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_category_time", "category", "create_time"),
        Index("ix_audit_logs_user", "user_id"),
        {"comment": "操作与登录日志"},
    )

    category: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="分类: login-登录 / operation-操作"
    )
    action: Mapped[str] = mapped_column(
        String(60), nullable=False, comment="动作代码, 如 login.success / lab.update"
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="操作人ID, 账号不存在时为空",
    )
    username: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="操作人账号快照"
    )
    target_type: Mapped[str | None] = mapped_column(
        String(30), nullable=True, comment="对象类型, 如 lab/reservation/user"
    )
    target_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="对象ID"
    )
    detail: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="补充说明"
    )
    ip: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="来源IP"
    )
