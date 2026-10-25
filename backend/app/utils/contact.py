"""邮箱 / 手机号的归一化与格式校验。

登录、注册、个人资料、管理员用户管理几处都要用同一套规则。分开写会出现
"资料页能存进去、登录时查不到"这种很难查的问题，所以统一放这里。
"""

import re

from app.common.exceptions import BusinessException

# 不用 pydantic 的 EmailStr：那要多装 email-validator，而这里只需要挡住
# 明显不是邮箱的输入。真正的可达性由验证码登录那一刻证明。
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


def normalize_email(value: str) -> str:
    """去空白、转小写并校验格式；不合法时抛业务异常。"""
    email = (value or "").strip().lower()
    if not _EMAIL_RE.fullmatch(email):
        raise BusinessException(message="邮箱格式不正确")
    return email


def normalize_phone(value: str) -> str:
    """去掉用户可能输入的空格 / 横线，再按大陆手机号校验。"""
    phone = re.sub(r"[\s\-]", "", value or "")
    if not _PHONE_RE.fullmatch(phone):
        raise BusinessException(message="手机号格式不正确")
    return phone


def normalize_optional_email(value: str | None) -> str | None:
    """资料里的邮箱可以为空；空串和纯空白都存成 NULL。"""
    if value is None:
        return None
    value = value.strip()
    return normalize_email(value) if value else None


def normalize_optional_phone(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return normalize_phone(value) if value else None
