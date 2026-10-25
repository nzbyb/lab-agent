from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.services import notification_service

router = APIRouter(prefix="/notification", tags=["消息通知"])


@router.get("/list")
def get_notification_page_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    unread_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    res = notification_service.get_notification_page_list(
        db, current_user, page, page_size, unread_only
    )
    return Response.success(data=res)


@router.get("/unread-count")
def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    count = notification_service.get_unread_count(db, current_user)
    return Response.success(data={"count": count})


@router.put("/read-all")
def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    count = notification_service.mark_all_read(db, current_user)
    # 返回实际标记了几条，"0 条"在界面上是"本来就没有未读"，不是失败。
    return Response.success(message="已全部标为已读", data={"count": count})


@router.put("/{notification_id}/read")
def mark_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification_service.mark_read(db, current_user, notification_id)
    return Response.success(message="已读")
