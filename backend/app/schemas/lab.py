from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 长度上限跟着 models/lab.py 的列宽走。超长字符串不在入口挡掉的话，
# 会一路走到 MySQL，在严格模式下抛 DataError 变成 500。
_NAME_MAX = 50
_DESCRIPTION_MAX = 500
_IMG_MAX = 100
_LOCATION_MAX = 100
_TIME_MAX = 20


def _looks_like_time(value: str) -> bool:
    """这个值长得像不像 HH:MM。

    下面那个"先后"校验只对真时间有意义。测试里有拿 "0"*20 这种填充值
    去顶长度上限的用例（它验的是列宽，不是时间），对那种值比大小是误伤。
    """
    try:
        datetime.strptime(value, "%H:%M")
    except ValueError:
        return False
    return True


def _check_hours_pair(open_time: str | None, close_time: str | None, label: str):
    """开门必须早于关门。

    以前完全没校验，管理端能把一间实验室存成"20:00 开门、18:00 关门"，
    之后所有预约和空闲时段查询都算不出来（区间是空的），却看不出哪里错了。
    只在两个值都给了、且都是合法 HH:MM 的时候比——更新接口是部分更新，
    只传一个时没法知道库里另一个是什么。
    """
    if not open_time or not close_time:
        return
    if not (_looks_like_time(open_time) and _looks_like_time(close_time)):
        return
    if close_time <= open_time:
        raise ValueError(f"{label}的关门时间必须晚于开门时间")


class LabResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    img: str | None = None
    location: str | None = None
    capacity: int
    open_time: str | None = None
    close_time: str | None = None
    weekend_open_time: str | None = None
    weekend_close_time: str | None = None
    status: int

    # 下面三个是算出来的，不对应数据库里的列，所以**故意不给默认值**：
    # 漏了它们就当场报错，而不是静默回一个"未开放"。
    # 只能由 lab_service.to_lab_response 产出——那是全项目唯一知道
    # "某一天该用哪套时段"的地方。
    today_open_time: str | None
    today_close_time: str | None
    open_now: bool

    model_config = ConfigDict(from_attributes=True)


class LabCreateRequest(BaseModel):
    name: str = Field(max_length=_NAME_MAX)
    description: str | None = Field(default=None, max_length=_DESCRIPTION_MAX)
    img: str | None = Field(default=None, max_length=_IMG_MAX)
    location: str | None = Field(default=None, max_length=_LOCATION_MAX)
    capacity: int = 0
    open_time: str | None = Field(default=None, max_length=_TIME_MAX)
    close_time: str | None = Field(default=None, max_length=_TIME_MAX)
    weekend_open_time: str | None = Field(default=None, max_length=_TIME_MAX)
    weekend_close_time: str | None = Field(default=None, max_length=_TIME_MAX)
    status: int = 1

    @model_validator(mode="after")
    def _check_hours(self):
        _check_hours_pair(self.open_time, self.close_time, "周中")
        _check_hours_pair(self.weekend_open_time, self.weekend_close_time, "周末")
        return self


class LabUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=_NAME_MAX)
    description: str | None = Field(default=None, max_length=_DESCRIPTION_MAX)
    img: str | None = Field(default=None, max_length=_IMG_MAX)
    location: str | None = Field(default=None, max_length=_LOCATION_MAX)
    capacity: int | None = None
    open_time: str | None = Field(default=None, max_length=_TIME_MAX)
    close_time: str | None = Field(default=None, max_length=_TIME_MAX)
    weekend_open_time: str | None = Field(default=None, max_length=_TIME_MAX)
    weekend_close_time: str | None = Field(default=None, max_length=_TIME_MAX)
    status: int | None = None

    @model_validator(mode="after")
    def _check_hours(self):
        _check_hours_pair(self.open_time, self.close_time, "周中")
        _check_hours_pair(self.weekend_open_time, self.weekend_close_time, "周末")
        return self
