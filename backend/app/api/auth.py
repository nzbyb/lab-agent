from fastapi import APIRouter, Depends, Request
from app.schemas.auth import (
    EmailCodeLoginRequest,
    LoginRequest,
    PasswordResetRequest,
    PhoneLoginRequest,
    RegisterRequest,
    SendEmailCodeRequest,
)
from sqlalchemy.orm import Session
from app.database import get_db
from app.common.response import Response
from app.dependencies.auth import get_current_user
from app.common.exceptions import BusinessException
from app.limiter import enforce_login_account_limit, limiter
from app.models.user import User
from app.services import audit_service, auth_service

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

    try:
        result = auth_service.login(db, data)
    except BusinessException as exc:
        # 失败也要留痕：连着 5 次失败被锁，日志里得看得出是谁在试。
        # 这时可能根本没有这个用户，所以只能记对方输入的账号名。
        audit_service.record(
            category=audit_service.CATEGORY_LOGIN,
            action="login.failure",
            username=data.username,
            detail=exc.message,
        )
        raise

    audit_service.record(
        category=audit_service.CATEGORY_LOGIN,
        action="login.success",
        user=result.user,
        detail="账号密码登录",
    )
    return Response.success(
        message="登录成功",
        data=result,
    )


@router.post("/logout")
def logout(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """退出登录。必须带当前令牌；返回之后这枚令牌就作废了。"""
    auth_service.logout(db, current_user)
    audit_service.record(
        category=audit_service.CATEGORY_LOGIN,
        action="login.logout",
        user=current_user,
        detail="主动退出登录",
    )
    return Response.success(message="已退出登录")


@router.post("/login/phone")
@limiter.limit("60/minute")
def login_by_phone(
    request: Request, data: PhoneLoginRequest, db: Session = Depends(get_db)
):
    # 跟账号登录共用同一条「IP + 标识」额度；标识这里是手机号。
    enforce_login_account_limit(request, data.phone)
    try:
        result = auth_service.login_by_phone(db, data)
    except BusinessException as exc:
        # 手机号可能没绑过任何账号，日志里只能记这个号码本身。
        audit_service.record(
            category=audit_service.CATEGORY_LOGIN,
            action="login.failure",
            username=data.phone,
            detail=f"手机号登录：{exc.message}",
        )
        raise
    audit_service.record(
        category=audit_service.CATEGORY_LOGIN,
        action="login.success",
        user=result.user,
        detail="手机号密码登录",
    )
    return Response.success(message="登录成功", data=result)


@router.post("/email-code")
@limiter.limit("10/minute")
def send_email_code(
    request: Request, data: SendEmailCodeRequest, db: Session = Depends(get_db)
):
    # 真正的按邮箱冷却在 verification_service 里（要查库），这条是按 IP 的兜底：
    # 每次发信都是一次 SMTP 外连，不能让同一个来源无限刷。
    result = auth_service.send_login_code(db, data)
    return Response.success(message="验证码已发送", data=result)


@router.post("/login/email-code")
@limiter.limit("60/minute")
def login_with_email_code(
    request: Request, data: EmailCodeLoginRequest, db: Session = Depends(get_db)
):
    enforce_login_account_limit(request, data.email)
    try:
        result = auth_service.login_with_email_code(db, data)
    except BusinessException as exc:
        audit_service.record(
            category=audit_service.CATEGORY_LOGIN,
            action="login.failure",
            username=data.email,
            detail=f"邮箱验证码登录：{exc.message}",
        )
        raise
    audit_service.record(
        category=audit_service.CATEGORY_LOGIN,
        action="login.success",
        user=result.user,
        detail="邮箱验证码登录",
    )
    return Response.success(message="登录成功", data=result)


@router.post("/register/email-code")
@limiter.limit("10/minute")
def send_register_email_code(
    request: Request, data: SendEmailCodeRequest, db: Session = Depends(get_db)
):
    # 跟登录验证码一样：按 IP 挡刷信，真正的 60 秒冷却在服务层按邮箱算。
    result = auth_service.send_register_code(db, data)
    return Response.success(message="验证码已发送", data=result)


@router.post("/register")
@limiter.limit("5/minute")
def register(request: Request, data: RegisterRequest, db: Session = Depends(get_db)):
    auth_service.register(db, data)
    audit_service.record(
        category=audit_service.CATEGORY_OPERATION,
        action="user.register",
        username=data.username,
        target_type="user",
        detail="自助注册",
    )
    return Response.success(
        message="注册成功",
    )


# ---------------------------------------------------------------------------
# 找回密码：邮箱验证码 → 直接设新密码
#
# 这套接口不需要登录态：忘记密码的人正是登不进来的那批人。
# 安全边界跟邮箱验证码登录完全一样——能收到这个邮箱的验证码，
# 就证明这个邮箱是你的；邮箱又已经唯一绑定到一个账号上。
# ---------------------------------------------------------------------------


@router.post("/password/email-code")
@limiter.limit("10/minute")
def send_password_reset_code(
    request: Request, data: SendEmailCodeRequest, db: Session = Depends(get_db)
):
    # 按 IP 挡刷信，真正的 60 秒冷却在 verification_service 里按邮箱算。
    result = auth_service.send_password_reset_code(db, data)
    return Response.success(message="验证码已发送", data=result)


@router.post("/password/reset")
@limiter.limit("5/minute")
def reset_password(
    request: Request, data: PasswordResetRequest, db: Session = Depends(get_db)
):
    # 跟登录共用「IP + 标识」额度：这里同样是一次会跑 bcrypt 的未鉴权入口，
    # 不限制就能拿它当撞库/耗 CPU 的入口。
    enforce_login_account_limit(request, data.email)
    auth_service.reset_password_with_code(db, data)
    audit_service.record(
        category=audit_service.CATEGORY_OPERATION,
        action="user.password_reset",
        username=data.email,
        detail="用邮箱验证码找回密码",
    )
    return Response.success(message="密码已重置，请用新密码登录")
