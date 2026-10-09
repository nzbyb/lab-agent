from pydantic import BaseModel, ConfigDict, Field

# 长度上限跟着 models/lab.py 的列宽走。超长字符串不在入口挡掉的话，
# 会一路走到 MySQL，在严格模式下抛 DataError 变成 500。
_NAME_MAX = 50
_DESCRIPTION_MAX = 500
_IMG_MAX = 100
_LOCATION_MAX = 100
_TIME_MAX = 20


class LabResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    img: str | None = None
    location: str | None = None
    capacity: int
    open_time: str | None = None
    close_time: str | None = None
    status: int

    model_config = ConfigDict(from_attributes=True)


class LabCreateRequest(BaseModel):
    name: str = Field(max_length=_NAME_MAX)
    description: str | None = Field(default=None, max_length=_DESCRIPTION_MAX)
    img: str | None = Field(default=None, max_length=_IMG_MAX)
    location: str | None = Field(default=None, max_length=_LOCATION_MAX)
    capacity: int = 0
    open_time: str | None = Field(default=None, max_length=_TIME_MAX)
    close_time: str | None = Field(default=None, max_length=_TIME_MAX)
    status: int = 1


class LabUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=_NAME_MAX)
    description: str | None = Field(default=None, max_length=_DESCRIPTION_MAX)
    img: str | None = Field(default=None, max_length=_IMG_MAX)
    location: str | None = Field(default=None, max_length=_LOCATION_MAX)
    capacity: int | None = None
    open_time: str | None = Field(default=None, max_length=_TIME_MAX)
    close_time: str | None = Field(default=None, max_length=_TIME_MAX)
    status: int | None = None
