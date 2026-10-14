from pydantic import BaseModel, Field

from app.schemas.user import LoginPassword, NewPassword, UserResponse


class LoginRequest(BaseModel):
    username: str = Field(max_length=50)
    # 登录用 LoginPassword 而不是 NewPassword：这里只卡上限，不卡下限，
    # 理由见 schemas/user.py 顶部那段。
    password: LoginPassword


class LoginResponse(BaseModel):
    token: str
    user: UserResponse


class RegisterRequest(BaseModel):
    username: str = Field(max_length=50)
    password: NewPassword
    name: str | None = Field(default=None, max_length=50)
