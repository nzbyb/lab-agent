"""对齐 labs 表的列注释

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-14

这条迁移**只改注释，不改结构、不动数据**。

起因：做"开放时间分周中/周末"那次，模型里的注释改了（open_time 从
"开放开始时间"改成"周中开放开始时间"，并给两列补上说明），但当时的库是
`Base.metadata.create_all` 建的，而它**只建缺失的表，给已有表改注释不管**。
于是库里的注释一直停在旧版本，跟代码对不上——`alembic check` 一比就报 5 处。

这正是"没有迁移框架"会留下的痕迹：结构变了它不管，注释变了它也不管，
而且**不会报错**，只能靠人去发现。装上 Alembic 之后这类差异会被自动比对出来。

之所以值得单独一条迁移、而不是关掉注释比对：
MySQL 里列注释是表结构的一部分（存在 information_schema.COLUMNS 里），
以后有人用 Navicat 直接看库，看到的是注释而不是模型代码。注释说错话
（比如把已经只管周中的 open_time 说成通用的"开放开始时间"）会误导人。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OPEN_TIME = sa.String(length=20)


def upgrade() -> None:
    op.alter_column(
        "labs",
        "open_time",
        existing_type=_OPEN_TIME,
        existing_nullable=True,
        comment="周中开放开始时间",
    )
    op.alter_column(
        "labs",
        "close_time",
        existing_type=_OPEN_TIME,
        existing_nullable=True,
        comment="周中开放结束时间",
    )
    op.alter_column(
        "labs",
        "weekend_open_time",
        existing_type=_OPEN_TIME,
        existing_nullable=True,
        comment="周末开放开始时间",
    )
    op.alter_column(
        "labs",
        "weekend_close_time",
        existing_type=_OPEN_TIME,
        existing_nullable=True,
        comment="周末开放结束时间",
    )
    op.alter_column(
        "labs",
        "status",
        existing_type=sa.Integer(),
        existing_nullable=False,
        comment="启用状态, 0-停用, 1-启用",
    )


def downgrade() -> None:
    """退回旧注释。注释是纯文档，回滚它没有实际意义，但 alembic 要求成对出现。"""
    op.alter_column(
        "labs",
        "open_time",
        existing_type=_OPEN_TIME,
        existing_nullable=True,
        comment="开放开始时间",
    )
    op.alter_column(
        "labs",
        "close_time",
        existing_type=_OPEN_TIME,
        existing_nullable=True,
        comment="开放结束时间",
    )
    op.alter_column(
        "labs",
        "weekend_open_time",
        existing_type=_OPEN_TIME,
        existing_nullable=True,
        comment=None,
    )
    op.alter_column(
        "labs",
        "weekend_close_time",
        existing_type=_OPEN_TIME,
        existing_nullable=True,
        comment=None,
    )
    op.alter_column(
        "labs",
        "status",
        existing_type=sa.Integer(),
        existing_nullable=False,
        comment="状态, 0-关闭, 1-开放",
    )
