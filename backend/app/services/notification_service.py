"""站内消息 + 邮件通知。

站内消息是主路径：先落库，用户的铃铛一定能看到。
邮件是**尽力而为**的副路径：在后台线程里发，失败只记日志，绝不把
"审核通过"这件事因为它拖慢、甚至回滚。

为什么不直接在请求里发：SMTP 超时是 10 秒（见 SMTP_TIMEOUT），
邮件服务器一抽风，管理员点"通过"就要转十秒圈。线程里发，请求立刻返回。
"""

import logging
import threading
from datetime import datetime

from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.common.response import PageResponse
from app.database import SessionLocal
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import NotificationResponse
from app.utils import mailer

logger = logging.getLogger(__name__)

# 这几种 type 只是给前端挑图标/配色用的，文案已经在下面拼好了。
TYPE_APPROVED = "audit_approved"
TYPE_REJECTED = "audit_rejected"
TYPE_FORCE_CANCELED = "force_canceled"
TYPE_AUTO_CANCELED = "auto_canceled"


def create_notification(
    db: Session,
    *,
    user_id: int,
    type: str,
    title: str,
    content: str,
    reservation_id: int | None = None,
) -> Notification:
    """把消息挂进当前事务。

    刻意**不 commit**：调用方（审核 / 取消）本来就有一个事务，
    消息必须和"预约状态变了"一起成功或一起失败。否则会出现
    "审核通过了，但用户没收到消息"这种对不上账的状态。
    """
    item = Notification(
        user_id=user_id,
        type=type,
        title=title,
        content=content,
        reservation_id=reservation_id,
    )
    db.add(item)
    return item


def dispatch_email(notification_id: int) -> None:
    """提交之后调用。没配 SMTP 就直接返回，不白起线程。"""
    if not mailer.is_configured():
        return
    threading.Thread(
        target=_send_email_safely,
        args=(notification_id,),
        daemon=True,
        name=f"notify-mail-{notification_id}",
    ).start()


def _send_email_safely(notification_id: int) -> None:
    """线程入口：自己开一个 Session，不复用请求里的那个。

    SQLAlchemy 的 Session 不是线程安全的，请求结束就 close 了；
    把 ORM 对象丢进线程里用，表现是随机的 DetachedInstanceError。
    """
    db = SessionLocal()
    try:
        notification = (
            db.query(Notification).filter(Notification.id == notification_id).first()
        )
        if not notification:
            return
        user = db.query(User).filter(User.id == notification.user_id).first()
        if not user or not user.email:
            return
        mailer.send_notification(
            user.email, notification.title, notification.content
        )
    except Exception as exc:  # noqa: BLE001 - 后台线程的异常没人接，只能记下来
        logger.warning("发送预约通知邮件失败: %s", type(exc).__name__)
    finally:
        db.close()


def get_notification_page_list(
    db: Session,
    current_user: User,
    page: int,
    page_size: int,
    unread_only: bool = False,
):
    query = db.query(Notification).filter(Notification.user_id == current_user.id)
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))
    total = query.count()
    items = (
        query.order_by(Notification.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PageResponse(
        list=[NotificationResponse.model_validate(item) for item in items],
        total=total,
    )


def get_unread_count(db: Session, current_user: User) -> int:
    return (
        db.query(Notification)
        .filter(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
        )
        .count()
    )


def mark_read(db: Session, current_user: User, notification_id: int) -> None:
    item = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        )
        .first()
    )
    if not item:
        raise BusinessException(message="消息不存在")
    # 已读再点一次也返回成功：前端可能是重复点击，没必要报错。
    if not item.is_read:
        item.is_read = True
        item.read_time = datetime.now()
        db.commit()


def mark_all_read(db: Session, current_user: User) -> int:
    count = (
        db.query(Notification)
        .filter(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
        )
        .update(
            {Notification.is_read: True, Notification.read_time: datetime.now()},
            synchronize_session=False,
        )
    )
    db.commit()
    return count
