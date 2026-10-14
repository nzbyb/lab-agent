import bcrypt

from app.common.exceptions import BusinessException

# bcrypt 自己处理不了超过 72 字节的输入：5.0 起是**直接抛 ValueError**
# （password cannot be longer than 72 bytes），不是静默截断。
#
# schema 层（app/schemas/user.py 的 NewPassword / LoginPassword）已经按字节拦过一道，
# 走接口的请求到不了这里。这里是第二道，防的是**绕过 schema 的调用点**：
# 命令行脚本、以后新加的接口、测试里直接调 service。少了它，那些地方拿到的是
# 一个 500「服务器内部错误」，而不是一句能看懂的话。
#
# ⚠️ 判据是字节数不是字符数，一个汉字 3 字节，见 schemas/user.py 顶部。
_BCRYPT_MAX_BYTES = 72


def _to_bcrypt_bytes(password: str) -> bytes:
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        raise BusinessException(
            message=f"密码最多 {_BCRYPT_MAX_BYTES} 字节（一个汉字算 3 字节）"
        )
    return raw


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_to_bcrypt_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        _to_bcrypt_bytes(password), hashed_password.encode("utf-8")
    )
