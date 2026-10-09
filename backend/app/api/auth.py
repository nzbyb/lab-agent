from fastapi import APIRouter, Depends, Request
from app.schemas.auth import LoginRequest
from app.schemas.auth import RegisterRequest
from sqlalchemy.orm import Session
from app.database import get_db
from app.common.response import Response
from app.limiter import limiter
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["权限验证"])


# 登录和注册是全后端仅有的两个「未鉴权但会跑 bcrypt」的入口。
# 不加限制的话既能无限撞库，又能拿单请求约 180ms 的 CPU 开销把服务打满。
# 注意：slowapi 要求在签名里有个名字正好是 request 的参数，别改名。
@router.post("/login")
@limiter.limit("5/minute")
def login(request: Request, data: LoginRequest, db: Session = Depends(get_db)):
    result = auth_service.login(db, data)

    return Response.success(
        message="登录成功",
        data=result,
    )


@router.post("/register")
@limiter.limit("5/minute")
def register(request: Request, data: RegisterRequest, db: Session = Depends(get_db)):
    auth_service.register(db, data)

    return Response.success(
        message="注册成功",
    )
