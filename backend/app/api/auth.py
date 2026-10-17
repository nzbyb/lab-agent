from fastapi import APIRouter, Depends, Request
from app.schemas.auth import LoginRequest
from app.schemas.auth import RegisterRequest
from sqlalchemy.orm import Session
from app.database import get_db
from app.common.response import Response
from app.limiter import enforce_login_account_limit, limiter
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["权限验证"])


# 登录和注册是全后端仅有的两个「未鉴权但会跑 bcrypt」的入口。
# 不加限制的话既能无限撞库，又能拿单请求约 180ms 的 CPU 开销把服务打满。
# 注意：slowapi 要求在签名里有个名字正好是 request 的参数，别改名。
@router.post("/login")
@limiter.limit("60/minute")
def login(request: Request, data: LoginRequest, db: Session = Depends(get_db)):
    # 真正管"一个账号被反复试密码"的是下面这条：5 次/分钟，按 IP + 账号。
    # 上面那个 60/分钟是按 IP 的兜底，挡"同一个 IP 换着账号撞库"；
    # 额度给得宽，是因为校园网、公司网几十个人共用一个出口 IP，
    # 按 IP 卡太紧会把一群互不相干的人一起锁住——这正是要修的"被误伤"。
    enforce_login_account_limit(request, data.username)

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
