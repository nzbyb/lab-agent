from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_date(value: str) -> str:
    """把日期统一成补零的 YYYY-MM-DD。

    冲突检测全靠字符串比大小，格式不统一就会漏判：
    "2026-10-9" 在字典序里比 "2026-10-10" 还大。
    """
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise ValueError("日期格式应为 YYYY-MM-DD")


def normalize_time(value: str) -> str:
    """把时间统一成补零的 HH:MM。

    这个是冲突检测的命门。重叠判断用的是字符串比较，而 "9:00" 和 "09:00"
    在字典序里是两个值——混着写就能绕过重叠判断，把同一时段约两次。
    """
    try:
        return datetime.strptime(value, "%H:%M").strftime("%H:%M")
    except ValueError:
        raise ValueError("时间格式应为 HH:MM")


class ReservationCreateRequest(BaseModel):
    lab_id: int
    equipment_id: int | None = None
    date: str
    start_time: str
    end_time: str
    # 跟着 models/reservation.py 的列宽（String(255)）走
    remark: str | None = Field(default=None, max_length=255)

    @field_validator("date")
    @classmethod
    def _normalize_date(cls, value: str) -> str:
        return normalize_date(value)

    @field_validator("start_time", "end_time")
    @classmethod
    def _normalize_time(cls, value: str) -> str:
        return normalize_time(value)


class ReservationResponse(BaseModel):
    id: int
    user_id: int
    user_name: str | None = None
    lab_id: int
    lab_name: str | None = None
    equipment_id: int | None = None
    equipment_name: str | None = None
    type: str | None = None
    date: str
    start_time: str
    end_time: str
    remark: str | None = None
    status: int
    # 时间线用的时间点。老数据没有审核/取消时间，就是 null。
    create_time: datetime | None = None
    audit_time: datetime | None = None
    cancel_time: datetime | None = None
    cancel_reason: str | None = None
    # 这一行对**当前登录用户**来说能不能点"取消"。
    # 放在后端算，前端就不用再抄一份"待审核随便取消、已通过看开始前 2 小时"的规则；
    # 两边各写一份，改了一边就会出现"按钮能点、点下去被拒"。
    can_cancel: bool = False

    model_config = ConfigDict(from_attributes=True)


class AuditReservationRequest(BaseModel):
    status: int


class ForceCancelRequest(BaseModel):
    """管理员强制取消：必须写原因，用户会在预约记录里看到这句话。"""

    reason: str = Field(max_length=100)

    @field_validator("reason")
    @classmethod
    def _strip_and_check(cls, value: str) -> str:
        value = (value or "").strip()
        if len(value) < 2:
            raise ValueError("请填写取消原因（至少 2 个字）")
        return value


class FreeSlotItem(BaseModel):
    start_time: str
    end_time: str


class ScheduleDay(BaseModel):
    """一周网格里的一天。

    open_time / close_time 为 None = 当天不开放（周末可能就是这样）。
    busy 只包含状态为待审核/已通过的预约，已拒绝和已取消的不占位。
    """

    date: str
    # 0=周一 … 6=周日，跟 datetime.weekday() 一致，前端不用再推一遍。
    weekday: int
    open_time: str | None = None
    close_time: str | None = None
    busy: list[FreeSlotItem] = []


class WeekScheduleResponse(BaseModel):
    lab_id: int
    lab_name: str
    equipment_id: int | None = None
    equipment_name: str | None = None
    start_date: str
    days: list[ScheduleDay] = []


class FreeSlotResponse(BaseModel):
    lab_id: int
    lab_name: str | None = None
    equipment_id: int | None = None
    equipment_name: str | None = None
    date: str
    open_time: str
    close_time: str
    slots: list[FreeSlotItem] = []
    busy: list[FreeSlotItem] = []
