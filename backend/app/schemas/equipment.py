from pydantic import BaseModel, ConfigDict, Field

# 长度上限跟着 models/equipment.py 的列宽走。超长字符串不在入口挡掉的话，
# 会一路走到 MySQL，在严格模式下抛 DataError 变成 500。
_NAME_MAX = 50
_DESCRIPTION_MAX = 500
_IMG_MAX = 200
_SPEC_MAX = 100


class EquipmentResponse(BaseModel):
    id: int
    lab_id: int
    lab_name: str | None = None
    name: str
    description: str | None = None
    img: str | None = None
    spec: str | None = None
    quantity: int
    status: int

    model_config = ConfigDict(from_attributes=True)


class EquipmentCreateRequest(BaseModel):
    lab_id: int
    name: str = Field(max_length=_NAME_MAX)
    description: str | None = Field(default=None, max_length=_DESCRIPTION_MAX)
    img: str | None = Field(default=None, max_length=_IMG_MAX)
    spec: str | None = Field(default=None, max_length=_SPEC_MAX)
    quantity: int = 1
    status: int = 1


class EquipmentUpdateRequest(BaseModel):
    lab_id: int | None = None
    name: str | None = Field(default=None, max_length=_NAME_MAX)
    description: str | None = Field(default=None, max_length=_DESCRIPTION_MAX)
    img: str | None = Field(default=None, max_length=_IMG_MAX)
    spec: str | None = Field(default=None, max_length=_SPEC_MAX)
    quantity: int | None = None
    status: int | None = None
