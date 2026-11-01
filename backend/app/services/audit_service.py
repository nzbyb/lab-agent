"""操作日志 / 登录日志。

三个刻意的选择：

1. **写日志用独立会话，并且吞掉自己的异常。** 审计是旁路：日志写失败不该让
   "审核通过"跟着失败，也不该把业务事务一起回滚。反过来，业务回滚了日志却还在
   （比如登录失败要抛异常）——那正是我们要的，失败行为本身必须留痕。
2. **IP 用 ContextVar 取，不改几十个函数签名。** 中间件在请求进来时塞一次，
   服务层随手就能读到。
3. **只记结果，不记密码和令牌。** detail 里只放人看得懂的一句话。
"""

import logging
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy.orm import Session

from app.common.response import PageResponse
from app.database import SessionLocal
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.audit import AuditLogResponse

logger = logging.getLogger(__name__)

CATEGORY_LOGIN = "login"
CATEGORY_OPERATION = "operation"

_request_ip: ContextVar[str | None] = ContextVar("audit_request_ip", default=None)


@contextmanager
def capture_ip(ip: str | None):
    token = _request_ip.set(ip)
    try:
        yield
    finally:
        _request_ip.reset(token)


def current_ip() -> str | None:
    return _request_ip.get()


def record(
    *,
    category: str,
    action: str,
    user: User | None = None,
    username: str | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    detail: str | None = None,
) -> None:
    """写一条日志。绝不抛异常，绝不提交调用方的事务。"""
    db: Session | None = None
    try:
        db = SessionLocal()
        db.add(
            AuditLog(
                category=category,
                action=action,
                # user 可能是刚被删掉的 ORM 对象，读属性前先取出来，
                # 免得到了下面 session 里变成"已经脱离会话"的脏对象。
                user_id=getattr(user, "id", None),
                username=username or getattr(user, "username", None),
                target_type=target_type,
                target_id=target_id,
                detail=(detail or "")[:500] or None,
                ip=current_ip(),
            )
        )
        db.commit()
    except Exception:
        logger.warning("写审计日志失败: %s", action, exc_info=True)
    finally:
        if db is not None:
            db.close()


def get_log_page_list(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    category: str | None = None,
    username: str | None = None,
    action: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> PageResponse:
    query = db.query(AuditLog)
    if category:
        query = query.filter(AuditLog.category == category)
    if username:
        query = query.filter(AuditLog.username.like(f"%{username.strip()}%"))
    if action:
        query = query.filter(AuditLog.action.like(f"%{action.strip()}%"))
    # 日期筛的是 create_time 的日期部分。用字符串比 "YYYY-MM-DD" 不够，
    # 因为 create_time 是 DateTime，交给 MySQL 的 DATE() 更直接。
    if start_date:
        query = query.filter(
            AuditLog.create_time >= f"{start_date} 00:00:00"
        )
    if end_date:
        # 结束日包含整天：不写到 23:59:59 的话，当天的日志一条都筛不出来。
        query = query.filter(AuditLog.create_time <= f"{end_date} 23:59:59")

    total = query.count()
    items = (
        query.order_by(AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PageResponse(
        list=[AuditLogResponse.model_validate(item) for item in items],
        total=total,
    )
