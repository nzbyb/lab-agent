from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings


def create_access_token(user_id: int, token_version: int) -> str:
    """签发令牌。

    `token_version` 是用户当前的令牌版本号（users.token_version），写进 `ver` 声明。
    校验时拿它跟库里那一列比，对不上就 401——改密码会把版本号 +1，于是旧令牌全废。

    这里**故意不给默认值**：漏传的地方会当场 TypeError（登录接口直接 500、测试全红），
    而不是悄悄签出一个 ver=0 的令牌、表现成"登录完立刻失效"这种难查的怪事。
    目前只有两个调用点：auth_service.login 和 tests/conftest.py 的 auth_headers。
    """
    # 必须用带时区的时间。PyJWT 会把不带时区的 datetime 当作 UTC，
    # 而 datetime.now() 是本地时间——在 UTC+8 上 token 会多活 8 小时。
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRE_HOURS)

    payload = {"user_id": user_id, "ver": token_version, "exp": expire}

    return jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def decode_access_token(token: str) -> dict:
    return jwt.decode(
        token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )
