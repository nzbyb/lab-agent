"""预约变更记录（时间线）

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-01

每变一次状态记一行。operator_id 允许为空：超时自动取消是后台扫描干的，
没有具体的人；管理员账号被删之后也靠 SET NULL 保住历史。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reservation_logs",
        sa.Column(
            "id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"
        ),
        sa.Column("reservation_id", sa.Integer(), nullable=False, comment="预约ID"),
        sa.Column(
            "action",
            sa.String(length=30),
            nullable=False,
            comment="动作: create/approve/reject/cancel/force_cancel/auto_cancel",
        ),
        sa.Column(
            "from_status", sa.Integer(), nullable=True, comment="变更前状态, 新建时为空"
        ),
        sa.Column("to_status", sa.Integer(), nullable=True, comment="变更后状态"),
        sa.Column(
            "operator_id",
            sa.Integer(),
            nullable=True,
            comment="操作人ID, 系统自动取消时为空",
        ),
        sa.Column(
            "operator_name", sa.String(length=50), nullable=True, comment="操作人名称快照"
        ),
        sa.Column(
            "reason", sa.String(length=255), nullable=True, comment="原因, 如强制取消的理由"
        ),
        sa.Column("create_time", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("update_time", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(
            ["reservation_id"], ["reservation.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["operator_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        comment="预约变更记录",
    )
    op.create_index(
        "ix_reservation_logs_reservation",
        "reservation_logs",
        ["reservation_id", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_reservation_logs_reservation", table_name="reservation_logs")
    op.drop_table("reservation_logs")
