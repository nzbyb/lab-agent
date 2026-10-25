"""站内消息表

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-25

预约状态变化时给本人留一条消息（审核通过 / 驳回 / 管理员取消 / 超时自动取消）。
表里只存"给谁、说什么、关联哪条预约、读没读"，不存邮件状态：
邮件是尽力而为的副路径，失败也不影响站内消息，没必要为它多两列。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("user_id", sa.Integer(), nullable=False, comment="接收人"),
        sa.Column(
            "type",
            sa.String(length=30),
            nullable=False,
            comment="类型: audit_approved/audit_rejected/force_canceled/auto_canceled",
        ),
        sa.Column("title", sa.String(length=100), nullable=False, comment="标题"),
        sa.Column("content", sa.String(length=500), nullable=False, comment="正文"),
        sa.Column(
            "reservation_id",
            sa.Integer(),
            nullable=True,
            comment="关联预约ID,仅用于跳转",
        ),
        sa.Column(
            "is_read",
            sa.Boolean(),
            server_default="0",
            nullable=False,
            comment="是否已读",
        ),
        sa.Column("read_time", sa.DateTime(), nullable=True, comment="阅读时间"),
        sa.Column("create_time", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("update_time", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="站内消息",
    )
    op.create_index(
        "ix_notifications_user_read",
        "notifications",
        ["user_id", "is_read"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_user_read", table_name="notifications")
    op.drop_table("notifications")
