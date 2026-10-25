"""邮箱验证码的签发与核销。

服务「登录」和「注册」两种场景。验证码写在 MySQL 里而不是 Redis：
项目本来就有 Alembic 和 MySQL，测试也走迁移；再为验证码引入一个可选依赖
（Redis 在本机/测试里是关掉的）只会多一条"换个环境就不工作"的路。
"""

import hashlib
import hmac
import math
import re
import secrets
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.config import settings
from app.models.user import User
from app.models.verification import VerificationCode
from app.utils import mailer
from app.utils.contact import normalize_email

LOGIN_SCENE = "login"
REGISTER_SCENE = "register"
# 找回密码单独一个场景：登录码不能拿来重置密码，重置码也不能拿去登录。
RESET_SCENE = "reset"
_CODE_RE = re.compile(r"^\d{6}$")


def _hash_code(email: str, code: str) -> str:
    # 用 JWT_SECRET_KEY 当 HMAC 的密钥：它已经是部署时必须配好的强随机值，
    # 不需要再让用户多管一个密钥。验证码本身是 6 位数字，哈希挡不住离线穷举，
    # 真正有效的是过期时间、尝试次数和一次一用。
    return hmac.new(
        settings.JWT_SECRET_KEY.encode("utf-8"),
        f"{email}:{code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _seconds_until_retry(latest: VerificationCode, now: datetime) -> int:
    elapsed = (now - latest.create_time).total_seconds()
    return max(0, math.ceil(settings.EMAIL_CODE_COOLDOWN_SECONDS - elapsed))


def _issue_code(
    db: Session,
    email: str,
    scene: str,
    send: Callable[[str, str], None],
) -> dict:
    """生成、存库并发送一枚验证码。登录和注册共用同一套冷却与落库规则。"""
    now = datetime.now()
    latest = (
        db.query(VerificationCode)
        .filter(
            VerificationCode.email == email,
            VerificationCode.scene == scene,
        )
        .order_by(VerificationCode.id.desc())
        .first()
    )
    if latest:
        wait = _seconds_until_retry(latest, now)
        if wait > 0:
            raise BusinessException(
                message=f"请 {wait} 秒后再获取验证码", code=429
            )

    code = f"{secrets.randbelow(1_000_000):06d}"
    # 新码一发出去，旧码立刻作废；不删的话用户可能翻出上一封邮件里的旧码。
    db.query(VerificationCode).filter(
        VerificationCode.email == email,
        VerificationCode.scene == scene,
    ).delete(synchronize_session=False)
    record = VerificationCode(
        email=email,
        scene=scene,
        code_hash=_hash_code(email, code),
        expires_at=now + timedelta(minutes=settings.EMAIL_CODE_EXPIRE_MINUTES),
        attempts=0,
        used=False,
    )
    db.add(record)
    db.flush()

    try:
        send(email, code)
    except Exception:
        # 邮件没发出去，验证码记录也不能留下：否则用户重试会被 60 秒冷却挡住，
        # 而他手里根本没有可用的码。
        db.rollback()
        raise

    db.commit()
    return {
        "cooldown": settings.EMAIL_CODE_COOLDOWN_SECONDS,
        "expires_in": settings.EMAIL_CODE_EXPIRE_MINUTES * 60,
    }


def _consume_code(db: Session, raw_email: str, raw_code: str, scene: str) -> str:
    """核销指定场景的验证码并返回归一化后的邮箱。

    成功、过期、错误次数超限都会把它标成已使用；只有"输错但还能再试"会保留，
    并把 attempts +1。行锁保证同一条验证码不会被两个并发请求同时核销。
    """
    email = normalize_email(raw_email)
    code = (raw_code or "").strip()
    if not _CODE_RE.fullmatch(code):
        raise BusinessException(message="验证码不正确，请检查后重试")

    record = (
        db.query(VerificationCode)
        .filter(
            VerificationCode.email == email,
            VerificationCode.scene == scene,
            VerificationCode.used.is_(False),
        )
        .order_by(VerificationCode.id.desc())
        .with_for_update()
        .first()
    )
    if not record:
        raise BusinessException(message="验证码已失效，请重新获取")

    now = datetime.now()
    if record.expires_at < now:
        record.used = True
        db.commit()
        raise BusinessException(message="验证码已过期，请重新获取")

    if record.attempts >= settings.EMAIL_CODE_MAX_ATTEMPTS:
        record.used = True
        db.commit()
        raise BusinessException(message="验证码错误次数过多，请重新获取", code=429)

    if not hmac.compare_digest(record.code_hash, _hash_code(email, code)):
        record.attempts += 1
        if record.attempts >= settings.EMAIL_CODE_MAX_ATTEMPTS:
            record.used = True
            db.commit()
            raise BusinessException(
                message="验证码错误次数过多，请重新获取", code=429
            )
        db.commit()
        raise BusinessException(message="验证码不正确，请检查后重试")

    record.used = True
    db.commit()
    return email


def send_login_code(db: Session, raw_email: str) -> dict:
    """给已绑定邮箱的账号发一枚登录验证码。"""
    email = normalize_email(raw_email)
    user = db.query(User).filter(User.email == email).first()
    if not user:
        # 这里说清楚比含糊更省事：用户打错邮箱时能马上改，而不是等一分钟
        # 才发现邮件永远收不到。代价是能被用来探某个邮箱有没有注册过，
        # 对一个校内实验室系统来说可以接受。
        raise BusinessException(message="该邮箱未绑定账号")
    if user.status != 1:
        raise BusinessException(message="账号被禁用")
    return _issue_code(db, email, LOGIN_SCENE, mailer.send_login_code)


def send_register_code(db: Session, raw_email: str) -> dict:
    """给还没被占用的邮箱发一枚注册验证码。"""
    email = normalize_email(raw_email)
    if db.query(User).filter(User.email == email).first():
        raise BusinessException(message="该邮箱已被注册")
    return _issue_code(db, email, REGISTER_SCENE, mailer.send_register_code)


def send_reset_code(db: Session, raw_email: str) -> dict:
    """给已绑定邮箱的账号发一枚找回密码验证码。

    跟登录码一样会明说"该邮箱未绑定账号"：这条信息本来就能从登录码接口问出来，
    这里再藏一次没有意义，只会让打错邮箱的人一直等一封永远不来的邮件。
    """
    email = normalize_email(raw_email)
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise BusinessException(message="该邮箱未绑定账号")
    if user.status != 1:
        raise BusinessException(message="账号被禁用")
    return _issue_code(db, email, RESET_SCENE, mailer.send_reset_code)


def consume_login_code(db: Session, raw_email: str, raw_code: str) -> str:
    return _consume_code(db, raw_email, raw_code, LOGIN_SCENE)


def consume_register_code(db: Session, raw_email: str, raw_code: str) -> str:
    return _consume_code(db, raw_email, raw_code, REGISTER_SCENE)


def consume_reset_code(db: Session, raw_email: str, raw_code: str) -> str:
    return _consume_code(db, raw_email, raw_code, RESET_SCENE)
