from pydantic import BaseModel, Field

from app.schemas.user import LoginPassword, NewPassword, UserResponse


class LoginRequest(BaseModel):
    username: str = Field(max_length=50)
    # 登录用 LoginPassword 而不是 NewPassword：这里只卡上限，不卡下限，
    # 理由见 schemas/user.py 顶部那段。
    password: LoginPassword


class PhoneLoginRequest(BaseModel):
    phone: str = Field(max_length=50)
    password: LoginPassword


class SendEmailCodeRequest(BaseModel):
    email: str = Field(max_length=100)


class EmailCodeLoginRequest(BaseModel):
    email: str = Field(max_length=100)
    # 不在 schema 里卡 6 位：格式不对也应该回"验证码不正确"，而不是
    # 一条跟验证码内容无关的 422。真正的校验在 verification_service 里。
    code: str = Field(max_length=10)


class PasswordResetRequest(BaseModel):
    """邮箱验证码自助重置密码。

    不带旧密码：忘记密码的人本来就不知道它。身份由"能收到这个邮箱的验证码"
    证明，跟邮箱登录是同一条信任链。
    """

    email: str = Field(max_length=100)
    code: str = Field(max_length=10)
    new_password: NewPassword


class LoginResponse(BaseModel):
    token: str
    user: UserResponse


class RegisterRequest(BaseModel):
    username: str = Field(max_length=50)
    password: NewPassword
    name: str | None = Field(default=None, max_length=50)
    # 邮箱和验证码都选了才走「邮箱注册」；不传仍兼容旧的账号+密码注册
    # （初始化脚本、老客户端都还这么调）。
    email: str | None = Field(default=None, max_length=100)
    code: str | None = Field(default=None, max_length=10)
