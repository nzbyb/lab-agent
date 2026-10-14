from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

# 长度上限都跟着 models/user.py 里的列宽走。不加的话超长字符串会一路
# 走到 MySQL，在严格模式下直接抛 DataError 变成 500；加上就是在入口
# 变成一条能看懂的 422。
_NAME_MAX = 50
_ROLE_MAX = 50

# ---------------------------------------------------------------------------
# 密码的长度边界。上限那一条不是"我们的规定"，是 bcrypt 的规定。
#
# bcrypt 5.0 碰到超过 72 字节的输入**直接抛异常**
# （ValueError: password cannot be longer than 72 bytes），不是老版本那种静默
# 截断。这个异常不属于 BusinessException，会一路冒到 global_exception_hadler，
# 于是用户看到的是 500「服务器内部错误」——注册一个长密码能把接口打成 500。
#
# ⚠️ 卡的是**字节数**，不是字符数。一个汉字在 UTF-8 里占 3 字节，所以 24 个汉字
# 就到顶了。写 len(value) > 72 会漏掉所有中文密码，而中文密码恰恰是最容易被
# 用户设出来的。
#
# 下限 3 沿用 UserCreateRequest 原先就有的 min_length，跟管理员「新增用户」
# 表单的规则保持一致。
PASSWORD_MIN_LENGTH = 3
PASSWORD_MAX_BYTES = 72


def _reject_over_long_password(value: str) -> str:
    if len(value.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise ValueError(
            f"密码最多 {PASSWORD_MAX_BYTES} 字节（一个汉字算 3 字节）"
        )
    return value


# 登录时用的类型：**刻意不带下限**。
# 卡下限会把老账号锁在门外——当年注册没卡过长度，库里真的存着短密码。
# 而且报出来的还是「请求参数校验错误」，跟密码对不对毫无关系，出了事根本查不出来。
# 上限必须有，因为 verify_password 一样会炸。
LoginPassword = Annotated[str, AfterValidator(_reject_over_long_password)]

# 设置新密码时用的类型。注册、管理员新建用户、本人改密码、管理员重置他人密码
# 四处共用同一份规则——分开写就会出现"注册能过的密码，改密码的时候过不了"
# 这种谁也说不清的现象。
NewPassword = Annotated[
    str,
    Field(min_length=PASSWORD_MIN_LENGTH),
    AfterValidator(_reject_over_long_password),
]


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
    # 原本是 password: str = "123"——不传密码就能建出一个拿 "123" 就能登录的账号。
    # 改成必填。只写「必填」还不够：password: "" 依然能过，等于还是能建出
    # 空密码的可登录账号，所以补一个下界，跟前端新建用户表单的规则对齐。
    # 上下界现在都在 NewPassword 里，见文件顶部。
    password: NewPassword
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
    """本人改密码。要验原密码，所以两条路都得挂上长度约束——
    old_password 不卡上限的话，拿一个 100 字节的"原密码"去撞接口，
    verify_password 会在 bcrypt 里炸成 500，而它本该只是一句"原密码错误"。"""

    old_password: LoginPassword
    new_password: NewPassword


class AdminPasswordResetRequest(BaseModel):
    """管理员给**别人**重置密码。

    跟 PasswordUpdateRequest 的区别就在这儿：没有 old_password，
    管理员本来也不该知道对方的原密码。所以这个请求体只能挂在管理员接口上，
    绝不能顺手复用到 /api/user/password 那条路上——复用等于把"改密码要先验原密码"
    这条规则取消了，任何拿到令牌的人都能改掉账号密码。
    """

    new_password: NewPassword
