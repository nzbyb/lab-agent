from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Favorite(Base):
    """实验室收藏。

    (user_id, lab_id) 建唯一索引而不是靠代码先查后插：连点两下心形、
    或两个标签页同时操作，都会走到这里，唯一索引是最后一道保证。
    """

    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "lab_id", name="uq_favorites_user_lab"),
        # 唯一索引已经覆盖了 user_id 前缀，这里补一条 lab_id 的：
        # 删实验室时要按 lab_id 级联，没有它得扫全表。
        Index("ix_favorites_lab", "lab_id"),
        {"comment": "实验室收藏"},
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="用户ID"
    )
    lab_id: Mapped[int] = mapped_column(
        ForeignKey("labs.id", ondelete="CASCADE"), nullable=False, comment="实验室ID"
    )


class LabView(Base):
    """实验室最近浏览。

    一个用户对同一间实验室只留一行，再看一次就把 view_time 刷到当下。
    **刻意不记流水**：浏览记录是给用户"快速回到刚才看的那间"用的，不是审计；
    记流水会让这张表涨得比预约表还快，却提供不了任何额外信息。
    """

    __tablename__ = "lab_views"
    __table_args__ = (
        UniqueConstraint("user_id", "lab_id", name="uq_lab_views_user_lab"),
        # 列表固定是"我的、按时间倒序取前 N 条"
        Index("ix_lab_views_user_time", "user_id", "view_time"),
        {"comment": "实验室浏览记录"},
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="用户ID"
    )
    lab_id: Mapped[int] = mapped_column(
        ForeignKey("labs.id", ondelete="CASCADE"), nullable=False, comment="实验室ID"
    )
    view_time: Mapped[datetime] = mapped_column(
        # 精确到微秒：只到秒的话，"再看一眼同一间实验室"和别的记录落在同一秒里，
        # 按 view_time 排序就会平手，最近浏览的顺序变得不确定。
        # 必须走 MySQL 方言的 DATETIME(fsp=6)：泛型 DateTime 的第一个位置参数是
        # timezone，写成 DateTime(6) 只会得到不带小数秒的 DATETIME——这个坑
        # 直到 CI 跑红才暴露。with_variant 让其他方言仍用普通 DateTime。
        DateTime().with_variant(MySQLDateTime(fsp=6), "mysql"),
        default=datetime.now,
        nullable=False,
        comment="最近浏览时间",
    )
