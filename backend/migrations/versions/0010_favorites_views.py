"""收藏与浏览记录

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-01

两张表都用 (user_id, lab_id) 唯一索引：收藏防"同一个人对同一间实验室插两行"，
浏览记录顺便就把"只留最后一次"的语义落到了库里。删人、删实验室都级联清掉。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "favorites",
        sa.Column(
            "id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"
        ),
        sa.Column("user_id", sa.Integer(), nullable=False, comment="用户ID"),
        sa.Column("lab_id", sa.Integer(), nullable=False, comment="实验室ID"),
        sa.Column("create_time", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("update_time", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lab_id"], ["labs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "lab_id", name="uq_favorites_user_lab"),
        comment="实验室收藏",
    )
    op.create_index("ix_favorites_lab", "favorites", ["lab_id"], unique=False)

    op.create_table(
        "lab_views",
        sa.Column(
            "id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"
        ),
        sa.Column("user_id", sa.Integer(), nullable=False, comment="用户ID"),
        sa.Column("lab_id", sa.Integer(), nullable=False, comment="实验室ID"),
        sa.Column(
            "view_time", sa.DateTime(6), nullable=False, comment="最近浏览时间"
        ),
        sa.Column("create_time", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("update_time", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lab_id"], ["labs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "lab_id", name="uq_lab_views_user_lab"),
        comment="实验室浏览记录",
    )
    op.create_index(
        "ix_lab_views_user_time", "lab_views", ["user_id", "view_time"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_lab_views_user_time", table_name="lab_views")
    op.drop_table("lab_views")
    op.drop_index("ix_favorites_lab", table_name="favorites")
    op.drop_table("favorites")
