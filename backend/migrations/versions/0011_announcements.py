"""公告

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-01

publisher_id 用 SET NULL：删掉管理员账号不该把公告一起带走。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column(
            "id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"
        ),
        sa.Column("title", sa.String(length=100), nullable=False, comment="标题"),
        sa.Column("content", sa.Text(), nullable=False, comment="正文"),
        sa.Column(
            "pinned",
            sa.Boolean(),
            server_default="0",
            nullable=False,
            comment="是否置顶",
        ),
        sa.Column(
            "status",
            sa.Integer(),
            server_default="1",
            nullable=False,
            comment="状态: 0-草稿, 1-已发布",
        ),
        sa.Column("publisher_id", sa.Integer(), nullable=True, comment="发布人ID"),
        sa.Column(
            "publisher_name", sa.String(length=50), nullable=True, comment="发布人名称快照"
        ),
        sa.Column("create_time", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("update_time", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(["publisher_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        comment="公告",
    )
    op.create_index(
        "ix_announcements_status_pinned",
        "announcements",
        ["status", "pinned", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_announcements_status_pinned", table_name="announcements")
    op.drop_table("announcements")
