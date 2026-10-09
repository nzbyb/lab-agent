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

    model_config = ConfigDict(from_attributes=True)


class AuditReservationRequest(BaseModel):
    status: int


class FreeSlotItem(BaseModel):
    start_time: str
    end_time: str


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
