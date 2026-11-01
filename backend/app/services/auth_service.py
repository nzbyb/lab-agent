from datetime import datetime, timedelta
from math import ceil

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.user import UserResponse
from app.schemas.auth import (
    EmailCodeLoginRequest,
    LoginRequest,
    LoginResponse,
    PasswordResetRequest,
    PhoneLoginRequest,
    RegisterRequest,
    SendEmailCodeRequest,
)
from app.services import verification_service
from app.utils.contact import normalize_optional_email, normalize_phone
from app.utils.password import verify_password, hash_password
from app.utils.jwt import create_access_token
from app.common.exceptions import BusinessException


# 连续错 5 次锁 15 分钟。跟限流（5 次/分钟，按 IP+账号）是两道不同的闸：
# 限流防的是"一分钟内猛打"，锁定防的是"慢慢试、试够一整晚"。
MAX_LOGIN_FAILURES = 5
LOGIN_LOCK_MINUTES = 15


def _lock_minutes_left(user: User, now: datetime | None = None) -> int:
    """还要锁几分钟；没锁返回 0。

    用 ceil 而不是四舍五入：还剩 30 秒时应该报"1 分钟"，报"0 分钟"等于
    告诉用户"可以试了"，但下一次请求仍然是拒绝的。
    """
    if not user.locked_until:
        return 0
    now = now or datetime.now()
    seconds = (user.locked_until - now).total_seconds()
    return max(0, ceil(seconds / 60))


def _ensure_not_locked(user: User) -> None:
    left = _lock_minutes_left(user)
    if left:
        raise BusinessException(message=f"密码错误次数过多，请 {left} 分钟后再试")


def _record_login_failure(db: Session, user: User) -> None:
    """记一次失败，够了就上锁。

    **必须单独 commit**：调用方紧接着要抛异常，异常会把整个会话回滚，
    不先落库的话这次失败就白记了，锁永远凑不满。
    """
    user.failed_login_count = (user.failed_login_count or 0) + 1
    if user.failed_login_count >= MAX_LOGIN_FAILURES:
        user.locked_until = datetime.now() + timedelta(minutes=LOGIN_LOCK_MINUTES)
        # 计数归零：锁解除后重新给满 5 次机会，否则解锁第一次错就又锁上。
        user.failed_login_count = 0
    db.commit()


def _clear_login_failure(user: User) -> None:
    """登录成功清零。不单独 commit，跟调用方那笔一起落地。"""
    user.failed_login_count = 0
    user.locked_until = None


def _login_response(user: User) -> LoginResponse:
    if user.status != 1:
        raise BusinessException(message="账号被禁用")
    token = create_access_token(user.id, user.token_version or 0)
    return LoginResponse(token=token, user=UserResponse.model_validate(user))


def logout(db: Session, current_user: User) -> None:
    """退出登录：令牌版本 +1，当前这枚令牌立刻作废。

    只清前端的 localStorage 是没用的——令牌本身还是一张到期前都能用的通行证，
    被复制走之后照样能登。版本号 +1 会让该用户此前签发的**所有**令牌一起失效，
    包括别的设备上的。这是有意的：退出登录最常见的场景就是"这台设备不再用了"，
    做不到只踢一台也没关系，重新登录一次即可。

    复用 token_version 也意味着 dependencies/auth.py 里那句错误文案必须
    写成中性的"登录已失效"，不能再说是"密码已变更"。
    """
    current_user.token_version = (current_user.token_version or 0) + 1
    db.commit()


def login(db: Session, data: LoginRequest):
    user = db.query(User).filter(User.username == data.username).first()
    # 验证账号以及密码是否正确
    if not user:
        raise BusinessException(message="账号或密码错误")
    # 锁定判断放在密码校验之前：锁着的账号连"密码对不对"都不该告诉对方。
    _ensure_not_locked(user)
    if not verify_password(data.password, user.password):
        _record_login_failure(db, user)
        raise BusinessException(message="账号或密码错误")
    if user.failed_login_count or user.locked_until:
        _clear_login_failure(user)
        db.commit()
    return _login_response(user)


def login_by_phone(db: Session, data: PhoneLoginRequest):
    phone = normalize_phone(data.phone)
    user = db.query(User).filter(User.phone == phone).first()
    if not user:
        # 跟账号登录一样，不区分"手机号不存在"和"密码错了"：否则可以拿它
        # 枚举出哪些手机号绑过账号。
        raise BusinessException(message="手机号或密码错误")
    _ensure_not_locked(user)
    if not verify_password(data.password, user.password):
        _record_login_failure(db, user)
        raise BusinessException(message="手机号或密码错误")
    if user.failed_login_count or user.locked_until:
        _clear_login_failure(user)
        db.commit()
    return _login_response(user)


def send_login_code(db: Session, data: SendEmailCodeRequest):
    return verification_service.send_login_code(db, data.email)


def send_register_code(db: Session, data: SendEmailCodeRequest):
    return verification_service.send_register_code(db, data.email)


def send_password_reset_code(db: Session, data: SendEmailCodeRequest):
    return verification_service.send_reset_code(db, data.email)


def reset_password_with_code(db: Session, data: PasswordResetRequest):
    """验完邮箱验证码后直接换密码。

    这里必须把 token_version +1，理由跟本人改密码、管理员重置密码两处一样：
    忘记密码的常见原因之一就是"号可能被别人登着"。只换哈希不废令牌的话，
    对方手里那枚令牌还能一直用到过期，重置等于没做。

    密码和版本号要在同一次 commit 落地，中途失败不能只改一半。
    """
    email = verification_service.consume_reset_code(db, data.email, data.code)
    user = db.query(User).filter(User.email == email).first()
    if not user:
        # 发码时查过一次，这里再查是防止这 5 分钟里邮箱被解绑。
        raise BusinessException(message="该邮箱未绑定账号")
    if user.status != 1:
        raise BusinessException(message="账号被禁用")
    user.password = hash_password(data.new_password)
    user.token_version = (user.token_version or 0) + 1
    # 邮箱验证码本身就证明了身份，顺带解锁：否则刚重置完密码的人
    # 还要再等 15 分钟才能登进来，会以为重置失败了。
    _clear_login_failure(user)
    db.commit()


def login_with_email_code(db: Session, data: EmailCodeLoginRequest):
    email = verification_service.consume_login_code(db, data.email, data.code)
    user = db.query(User).filter(User.email == email).first()
    if not user:
        # 发码时已经查过一次，这里再查是防止这 5 分钟里邮箱被解绑。
        raise BusinessException(message="该邮箱未绑定账号")
    return _login_response(user)


def register(db: Session, data: RegisterRequest):
    user = db.query(User).filter(User.username == data.username).first()
    if user:
        raise BusinessException(message="账号已存在")

    email = normalize_optional_email(data.email)
    if email:
        if not (data.code or "").strip():
            raise BusinessException(message="请输入邮箱验证码")
        if db.query(User).filter(User.email == email).first():
            raise BusinessException(message="该邮箱已被注册")
        # 验证码核销会单独提交。先查用户名和邮箱，避免一上来就把码用掉。
        verification_service.consume_register_code(db, email, data.code)

    user_model = User(
        username=data.username,
        password=hash_password(data.password),
        name=data.name or data.username,
        email=email,
        role="student",
        status=1,
    )
    db.add(user_model)
    try:
        db.commit()
    except IntegrityError as exc:
        # 并发下两个人可能同时用同一个用户名/邮箱注册，唯一索引会在这里拦住。
        db.rollback()
        if db.query(User).filter(User.username == data.username).first():
            raise BusinessException(message="账号已存在") from exc
        if email and db.query(User).filter(User.email == email).first():
            raise BusinessException(message="该邮箱已被注册") from exc
        raise BusinessException(message="账号或邮箱已存在") from exc
    db.refresh(user_model)
