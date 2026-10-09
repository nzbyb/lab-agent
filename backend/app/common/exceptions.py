from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.common.response import Response


class BusinessException(Exception):
    def __init__(self, message: str, code: int = 500):
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
