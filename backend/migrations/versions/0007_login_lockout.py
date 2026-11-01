"""登录失败锁定

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-01

连续错 5 次密码锁 15 分钟。两列都给 server_default，老行不用回填也能直接用：
failed_login_count 补 0（=从没错过），locked_until 留 NULL（=没锁）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "failed_login_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="连续密码错误次数, 登录成功后清零",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "locked_until",
            sa.DateTime(),
            nullable=True,
            comment="锁定到此刻为止, 空表示未锁定",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
