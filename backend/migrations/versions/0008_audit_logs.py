"""操作日志与登录日志

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-01

一张表装两类事件（category 区分 login / operation）。user_id 可空且
ON DELETE SET NULL：账号不存在的登录失败也要记，删用户时日志不能跟着没。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column(
            "id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"
        ),
        sa.Column(
            "category",
            sa.String(length=20),
            nullable=False,
            comment="分类: login-登录 / operation-操作",
        ),
        sa.Column(
            "action",
            sa.String(length=60),
            nullable=False,
            comment="动作代码, 如 login.success / lab.update",
        ),
        sa.Column(
            "user_id", sa.Integer(), nullable=True, comment="操作人ID, 账号不存在时为空"
        ),
        sa.Column(
            "username", sa.String(length=50), nullable=True, comment="操作人账号快照"
        ),
        sa.Column(
            "target_type",
            sa.String(length=30),
            nullable=True,
            comment="对象类型, 如 lab/reservation/user",
        ),
        sa.Column("target_id", sa.Integer(), nullable=True, comment="对象ID"),
        sa.Column("detail", sa.String(length=500), nullable=True, comment="补充说明"),
        sa.Column("ip", sa.String(length=64), nullable=True, comment="来源IP"),
        sa.Column("create_time", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("update_time", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        comment="操作与登录日志",
    )
    op.create_index(
        "ix_audit_logs_category_time",
        "audit_logs",
        ["category", "create_time"],
        unique=False,
    )
    op.create_index("ix_audit_logs_user", "audit_logs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_logs_user", table_name="audit_logs")
    op.drop_index("ix_audit_logs_category_time", table_name="audit_logs")
    op.drop_table("audit_logs")
