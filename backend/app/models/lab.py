from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Lab(Base):
    __tablename__ = "labs"
    __table_args__ = {"comment": "实验室信息"}

    name: Mapped[str] = mapped_column(String(50), comment="名称")
    description: Mapped[str] = mapped_column(String(500), comment="简介", nullable=True)
    img: Mapped[str] = mapped_column(String(100), comment="封面", nullable=True)
    location: Mapped[str] = mapped_column(String(100), comment="位置", nullable=True)
    capacity: Mapped[int] = mapped_column(Integer, comment="容量", default=0)
    # 下面两列是**周中（周一~周五）**的时段，周末另有两列。
    # 具体的"某一天用哪一套"只在 lab_service.resolve_open_hours 里判断一处。
    open_time: Mapped[str] = mapped_column(
        String(20), comment="周中开放开始时间", nullable=True
    )
    close_time: Mapped[str] = mapped_column(
        String(20), comment="周中开放结束时间", nullable=True
    )
    # 周末时段。两列都为空（NULL 或空字符串）就表示周末不开放。
    # 空字符串是历史包袱：管理端表单里清空时间选择器发上来的是 ''，不是 null，
    # 所以判断"有没有设"一律用真假值，不能只判 None。
    weekend_open_time: Mapped[str] = mapped_column(
        String(20), comment="周末开放开始时间", nullable=True
    )
    weekend_close_time: Mapped[str] = mapped_column(
        String(20), comment="周末开放结束时间", nullable=True
    )
    # 这是"管理员有没有启用这间实验室"，**不是**"此刻是否在开放时段内"。
    # 两回事：启用着的实验室，晚上照样是关门的。展示给用户时别写成"开放中"。
    status: Mapped[int] = mapped_column(
        Integer, comment="启用状态, 0-停用, 1-启用", default=1
    )
