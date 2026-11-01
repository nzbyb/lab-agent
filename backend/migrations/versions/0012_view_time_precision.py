"""最近浏览时间补上微秒

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-01

0010 里写的是 sa.DateTime(6)，但泛型 DateTime 的第一个位置参数是 timezone，
不是精度——建出来的列其实是不带小数秒的 DATETIME。同一秒里的多次浏览
按 view_time 排序会平手，"最近浏览"的顺序因此不确定，测试也会时红时绿。

这里只改精度，不动数据；旧的 datetime 值会补零到 .000000。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "lab_views",
        "view_time",
        existing_type=sa.DateTime(),
        type_=mysql.DATETIME(fsp=6),
        existing_nullable=False,
        existing_comment="最近浏览时间",
    )


def downgrade() -> None:
    # 回退会丢掉微秒（只保留到秒），这是这条迁移唯一有损的地方。
    op.alter_column(
        "lab_views",
        "view_time",
        existing_type=mysql.DATETIME(fsp=6),
        type_=sa.DateTime(),
        existing_nullable=False,
        existing_comment="最近浏览时间",
    )
