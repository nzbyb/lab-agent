from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class VerificationCode(Base):
    """邮箱验证码。

    只存哈希，不存明文：数据库被人翻到也拿不到还能用的验证码。
    6 位数字本来就能暴力枚举，所以真正的防线是"5 分钟过期 + 最多试 5 次 +
    用一次就作废"，而不是哈希本身。
    """

    __tablename__ = "verification_codes"
    __table_args__ = (
        Index("ix_verification_codes_email_scene", "email", "scene"),
        {"comment": "邮箱验证码"},
    )

    email: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="收件邮箱"
    )
    scene: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="login",
        server_default="login",
        comment="场景: login-登录",
    )
    code_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="验证码哈希"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="过期时间"
    )
    attempts: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default="0", comment="已输错次数"
    )
    used: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="0", comment="是否已使用"
    )
