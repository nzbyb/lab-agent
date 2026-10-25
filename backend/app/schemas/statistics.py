from datetime import datetime

from pydantic import BaseModel


class TrendPoint(BaseModel):
    """趋势图上的一天"""

    date: str
    count: int


class LabRankItem(BaseModel):
    """实验室排行里的一项"""

    lab_id: int
    lab_name: str
    count: int


class StatisticsOverviewResponse(BaseModel):
    """首页统计概览。

    全部字段都有默认值：空库时接口也要正常返回全 0，而不是抛异常。
    这个模型不是 ORM 映射（数据是几条聚合查询拼出来的），所以不设 from_attributes。
    字段名走项目既有的「扁平 + 前缀」风格（跟 ReservationResponse 一致），不嵌套。
    """

    lab_total: int = 0
    lab_open_total: int = 0
    equipment_total: int = 0
    equipment_normal_total: int = 0
    equipment_repair_total: int = 0
    reservation_total: int = 0
    reservation_pending_total: int = 0
    reservation_approved_total: int = 0
    reservation_rejected_total: int = 0
    reservation_canceled_total: int = 0
    reservation_trend: list[TrendPoint] = []
    lab_ranking: list[LabRankItem] = []


class PendingReservationItem(BaseModel):
    """管理员工作台上"等得最久的几条"。"""

    id: int
    user_name: str | None = None
    lab_name: str | None = None
    equipment_name: str | None = None
    date: str
    start_time: str
    end_time: str
    create_time: datetime | None = None


class AdminWorkbenchResponse(BaseModel):
    """管理端首页待办数据。只给管理员调，数据范围是全库。

    四个计数分开给，前端才能分别写"待审核 / 今日预约 / 今日待审核 / 近 7 天自动取消"。
    没有合并成一个"待办数"：这些数字的紧急程度不同，堆成一个数字反而看不出先做哪件。
    """

    pending_total: int = 0
    today_total: int = 0
    today_pending_total: int = 0
    auto_canceled_7d: int = 0
    pending_list: list[PendingReservationItem] = []
