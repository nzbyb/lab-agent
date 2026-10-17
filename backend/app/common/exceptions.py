import math
import time

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.common.response import Response


class BusinessException(Exception):
    """业务上"这次操作没做成"，比如账号密码不对、实验室已被预约。

    默认码是 **400**（不是 500）。这套接口把业务错误包在 HTTP 200 里、用
    body 里的 code 表示结果，所以这个码就是给前端看的判断依据，得能分清
    "你的请求有问题"和"服务器自己出问题了"：

        400  业务规则不允许（默认，占绝大多数）
        401  没登录 / 令牌失效
        403  登录了但没权限
        422  参数校验没过
        429  触发限流
        500  **真正的服务端故障**，由下面的全局兜底处理，业务代码不该主动抛

    改这个默认值之前，56 处业务错误全都回的是 500，于是"密码输错了"在接口
    层面报的是"服务器错误"——语义是错的，排查时也会把人往错的方向带。
    只有 3 处（无权限类）显式传了 403，现在它们仍然是各自的 403。
    """

    def __init__(self, message: str, code: int = 400):
        self.message = message
        self.code = code
        super().__init__(message)


async def business_exception_hadler(request: Request, exc: BusinessException):
    return JSONResponse(
        status_code=200,
        content=Response.error(code=exc.code, message=exc.message).model_dump(),
    )


async def http_exception_hadler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=Response.error(code=exc.status_code, message=exc.detail).model_dump(),
    )


async def validation_exception_hadler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=Response.error(code=422, message="请求参数校验错误").model_dump(),
    )


def _retry_after_seconds(request: Request, exc: RateLimitExceeded) -> int:
    """这枚额度还要多少秒才恢复。

    优先问存储要精确的重置时刻（slowapi 在触发限流前会把「是哪条额度、按什么 key
    算的」放在 request.state.view_rate_limit 里）；问不到就退回额度的整窗长度。
    两个都拿不到时给 60 秒——比让小气地报 1 秒、结果一重试又 429 好。
    """
    view = getattr(request.state, "view_rate_limit", None)
    if view:
        try:
            item, identifiers = view
            app_limiter = getattr(request.app.state, "limiter", None)
            stats = app_limiter.limiter.get_window_stats(item, *identifiers)
            return max(1, math.ceil(stats.reset_time - time.time()))
        except Exception:
            pass

    # exc.limit 是 slowapi 的 Limit 包装，里面那个才是 limits 的额度对象
    limit = getattr(exc, "limit", None)
    limit = getattr(limit, "limit", limit)
    try:
        return max(1, int(limit.get_expiry()))
    except Exception:
        return 60


async def rate_limit_exception_hadler(request: Request, exc: RateLimitExceeded):
    """限流触发。

    这里是全项目唯一用 HTTP 429 而不是 200 的地方，故意的：
    限流是基础设施层面的信号，得让反向代理和监控按状态码就直接认出来，
    不能塞进 body.code 里等着谁去解包。

    还要带上 `Retry-After`（秒）：没有它，前端只能干巴巴地说"太频繁了"，
    用户不知道等三秒还是等一分钟，最容易的做法就是立刻再点——继续吃 429。
    body 里的提示也把秒数写出来，前端两个地方都能直接显示。
    """
    retry_after = _retry_after_seconds(request, exc)
    return JSONResponse(
        status_code=429,
        content=Response.error(
            code=429, message=f"操作过于频繁，请 {retry_after} 秒后再试"
        ).model_dump(),
        headers={"Retry-After": str(retry_after)},
    )


async def global_exception_hadler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content=Response.error(code=500, message="服务器内部错误").model_dump(),
    )
