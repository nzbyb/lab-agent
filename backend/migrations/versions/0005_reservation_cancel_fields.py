"""预约增加审核时间、取消时间和取消原因

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-25

「我的预约」时间线要显示每一步是什么时候发生的，管理员强制取消还要把原因
留给用户看。这三样都不能用既有的 update_time 顶替：

- update_time 任何写入都会变，时间线会跟着漂。
- remark 是用户自己填的备注，拿去存取消原因会把人家的内容覆盖掉。

所以单独加三列。老数据里 audit_time / cancel_time 都是 NULL，时间线上就只
显示"提交"这一步，不会凭空编一个时间出来。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reservation",
        sa.Column("audit_time", sa.DateTime(), nullable=True, comment="审核时间"),
    )
    op.add_column(
        "reservation",
        sa.Column("cancel_time", sa.DateTime(), nullable=True, comment="取消时间"),
    )
    op.add_column(
        "reservation",
        sa.Column(
            "cancel_reason", sa.String(length=255), nullable=True, comment="取消原因"
        ),
    )


def downgrade() -> None:
    op.drop_column("reservation", "cancel_reason")
    op.drop_column("reservation", "cancel_time")
    op.drop_column("reservation", "audit_time")
