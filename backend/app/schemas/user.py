from pydantic import BaseModel, ConfigDict, Field

# 长度上限都跟着 models/user.py 里的列宽走。不加的话超长字符串会一路
# 走到 MySQL，在严格模式下直接抛 DataError 变成 500；加上就是在入口
# 变成一条能看懂的 422。
_NAME_MAX = 50
_ROLE_MAX = 50


class UserResponse(BaseModel):
    id: int
    username: str
    name: str
    role: str
    email: str | None = None
    phone: str | None = None
    avatar: str | None = None
    status: int

    model_config = ConfigDict(from_attributes=True)


class UserCreateRequest(BaseModel):
    username: str = Field(max_length=_NAME_MAX)
    password: str = "123"
    name: str | None = Field(default=None, max_length=_NAME_MAX)
    email: str | None = Field(default=None, max_length=_NAME_MAX)
    phone: str | None = Field(default=None, max_length=_NAME_MAX)
    avatar: str | None = Field(default=None, max_length=_NAME_MAX)
    role: str = Field(default="student", max_length=_ROLE_MAX)
    status: int = 1


class UserUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=_NAME_MAX)
    email: str | None = Field(default=None, max_length=_NAME_MAX)
    phone: str | None = Field(default=None, max_length=_NAME_MAX)
    avatar: str | None = Field(default=None, max_length=_NAME_MAX)
    role: str | None = Field(default=None, max_length=_ROLE_MAX)
    status: int | None = None


class PasswordUpdateRequest(BaseModel):
    old_password: str
    new_password: str
