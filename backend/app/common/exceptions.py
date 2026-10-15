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


async def rate_limit_exception_hadler(request: Request, exc: RateLimitExceeded):
    """限流触发。

    这里是全项目唯一用 HTTP 429 而不是 200 的地方，故意的：
    限流是基础设施层面的信号，得让反向代理和监控按状态码就直接认出来，
    不能塞进 body.code 里等着谁去解包。
    """
    return JSONResponse(
        status_code=429,
        content=Response.error(
            code=429, message="操作过于频繁，请稍后再试"
        ).model_dump(),
    )


async def global_exception_hadler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content=Response.error(code=500, message="服务器内部错误").model_dump(),
    )
