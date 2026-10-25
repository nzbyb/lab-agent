"""发邮件。只用标准库 smtplib，不为这一件事多装一个依赖。"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from app.common.exceptions import BusinessException
from app.config import settings

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(
        settings.SMTP_HOST.strip()
        and settings.SMTP_USER.strip()
        and settings.SMTP_PASSWORD.strip()
    )


def _build_message(to: str, subject: str, body: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = f"【智能实验室预约系统】{subject}"
    message["From"] = formataddr(
        (settings.SMTP_FROM_NAME or "智能实验室预约系统", settings.SMTP_USER)
    )
    message["To"] = to
    message.set_content(body)
    return message


def _deliver(message: EmailMessage) -> None:
    """真正连 SMTP 发出去。连不上就抛原始异常，由调用方决定怎么处理。"""
    if settings.SMTP_USE_SSL:
        client = smtplib.SMTP_SSL(
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            timeout=settings.SMTP_TIMEOUT,
            context=ssl.create_default_context(),
        )
    else:
        client = smtplib.SMTP(
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            timeout=settings.SMTP_TIMEOUT,
        )
        client.starttls(context=ssl.create_default_context())

    with client:
        client.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        client.send_message(message)


def _send_code(email: str, code: str, subject: str, action: str) -> None:
    """把验证码发到指定邮箱。

    这里刻意只记异常类型、不记异常原文：SMTP 的报错里可能带着收件地址，
    而日志会进 docker logs。配置缺失也当成业务错误，不要把 .env 的内容
    拼进返回给前端的话里。
    """
    if not is_configured():
        raise BusinessException(message="邮件服务未配置，暂时无法使用邮箱验证码")

    message = _build_message(
        email,
        subject,
        (
            f"你的{action}验证码是：{code}\n\n"
            f"{settings.EMAIL_CODE_EXPIRE_MINUTES} 分钟内有效，只能使用一次。\n"
            "如果这不是你本人的操作，请忽略这封邮件。"
        ),
    )

    try:
        _deliver(message)
    except Exception as exc:
        logger.warning("发送验证码失败: %s", type(exc).__name__)
        raise BusinessException(message="验证码发送失败，请稍后重试") from exc


def send_notification(email: str, subject: str, content: str) -> bool:
    """预约状态通知邮件。

    跟验证码不同，这里**不抛业务异常**：通知邮件是副路径，发不出去也不该
    影响"审核已经完成"这个事实。调用方在后台线程里跑，返回值只用于日志/测试。
    """
    if not is_configured():
        return False

    message = _build_message(
        email,
        subject,
        f"{content}\n\n本邮件由智能实验室预约系统自动发送，请勿直接回复。",
    )
    try:
        _deliver(message)
        return True
    except Exception as exc:
        logger.warning("发送通知邮件失败: %s", type(exc).__name__)
        return False


def send_login_code(email: str, code: str) -> None:
    _send_code(email, code, "登录验证码", "登录")


def send_register_code(email: str, code: str) -> None:
    _send_code(email, code, "注册验证码", "注册")


def send_reset_code(email: str, code: str) -> None:
    _send_code(email, code, "重置密码验证码", "重置密码")
