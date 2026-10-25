"""手机号 / 邮箱登录：验证码表 + 邮箱手机号唯一索引

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25

两件事：

1. 新建 `verification_codes`，存邮箱登录验证码的哈希、过期时间、尝试次数。
2. 给 `users.email` / `users.phone` 加唯一索引。没有唯一约束时，
   同一个手机号可以绑到两个账号上，登录查出来的是哪一个全看数据库心情。

加唯一索引之前先规整老数据：
- 空字符串要变成 NULL。MySQL 的唯一索引允许多个 NULL，但只允许一个空字符串；
  前端清空输入框发过来的是 ""，不处理的话第二个空邮箱就会撞索引。
- 邮箱统一小写，避免大小写不同被当成两个不同的地址。

如果库里已经有重复的邮箱/手机号，这条迁移会直接失败——这是故意的，
让部署的人先处理数据，而不是让登录悄悄落到错误的账号上。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _assert_no_duplicates(bind) -> None:
    for column in ("email", "phone"):
        duplicates = bind.execute(
            sa.text(
                f"""
                SELECT COUNT(*) FROM (
                    SELECT LOWER(TRIM({column})) AS value
                    FROM users
                    WHERE {column} IS NOT NULL AND TRIM({column}) <> ''
                    GROUP BY LOWER(TRIM({column}))
                    HAVING COUNT(*) > 1
                ) AS duplicated
                """
            )
        ).scalar()
        if duplicates:
            raise RuntimeError(
                f"users.{column} 存在重复值，无法加唯一索引；请先人工合并重复账号"
            )


def upgrade() -> None:
    op.create_table(
        "verification_codes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("email", sa.String(length=100), nullable=False, comment="收件邮箱"),
        sa.Column(
            "scene",
            sa.String(length=20),
            server_default="login",
            nullable=False,
            comment="场景: login-登录",
        ),
        sa.Column("code_hash", sa.String(length=64), nullable=False, comment="验证码哈希"),
        sa.Column("expires_at", sa.DateTime(), nullable=False, comment="过期时间"),
        sa.Column(
            "attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="已输错次数",
        ),
        sa.Column(
            "used",
            sa.Boolean(),
            server_default="0",
            nullable=False,
            comment="是否已使用",
        ),
        sa.Column("create_time", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("update_time", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        comment="邮箱验证码",
    )
    op.create_index(
        "ix_verification_codes_email_scene",
        "verification_codes",
        ["email", "scene"],
        unique=False,
    )

    bind = op.get_bind()
    _assert_no_duplicates(bind)

    op.execute(
        "UPDATE users SET email = NULL WHERE email IS NOT NULL AND TRIM(email) = ''"
    )
    op.execute(
        "UPDATE users SET phone = NULL WHERE phone IS NOT NULL AND TRIM(phone) = ''"
    )
    op.execute(
        "UPDATE users SET email = LOWER(TRIM(email)) WHERE email IS NOT NULL"
    )
    op.execute("UPDATE users SET phone = TRIM(phone) WHERE phone IS NOT NULL")

    op.create_unique_constraint("uq_users_email", "users", ["email"])
    op.create_unique_constraint("uq_users_phone", "users", ["phone"])


def downgrade() -> None:
    op.drop_constraint("uq_users_phone", "users", type_="unique")
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.drop_index(
        "ix_verification_codes_email_scene", table_name="verification_codes"
    )
    op.drop_table("verification_codes")
