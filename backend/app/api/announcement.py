from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_admin, get_current_user
from app.models.user import User
from app.schemas.announcement import (
    AnnouncementCreateRequest,
    AnnouncementUpdateRequest,
)
from app.services import announcement_service, audit_service

router = APIRouter(prefix="/announcement", tags=["公告"])


def _can_see_draft(user: User, include_draft: bool) -> bool:
    """草稿只给管理员看。学生就算在 URL 里塞 include_draft=true 也没用。"""
    return include_draft and user.role == "admin"


@router.get("/list")
def get_announcement_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    keyword: str | None = None,
    include_draft: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    res = announcement_service.get_announcement_page_list(
        db,
        page=page,
        page_size=page_size,
        include_draft=_can_see_draft(current_user, include_draft),
        keyword=keyword,
    )
    return Response.success(data=res)


@router.get("/{announcement_id}")
def get_announcement(
    announcement_id: int,
    include_draft: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    res = announcement_service.get_announcement(
        db, announcement_id, include_draft=_can_see_draft(current_user, include_draft)
    )
    return Response.success(data=res)


@router.post("")
def create_announcement(
    data: AnnouncementCreateRequest,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    res = announcement_service.create_announcement(db, current_user, data)
    audit_service.record(
        category=audit_service.CATEGORY_OPERATION,
        action="announcement.create",
        user=current_user,
        target_type="announcement",
        target_id=res.id,
        detail=f"发布公告「{res.title}」",
    )
    return Response.success(message="公告已发布", data=res)


@router.put("/{announcement_id}")
def update_announcement(
    announcement_id: int,
    data: AnnouncementUpdateRequest,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    res = announcement_service.update_announcement(db, announcement_id, data)
    audit_service.record(
        category=audit_service.CATEGORY_OPERATION,
        action="announcement.update",
        user=current_user,
        target_type="announcement",
        target_id=announcement_id,
        detail=f"修改公告「{res.title}」",
    )
    return Response.success(message="已保存", data=res)


@router.delete("/{announcement_id}")
def delete_announcement(
    announcement_id: int,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    announcement_service.delete_announcement(db, announcement_id)
    audit_service.record(
        category=audit_service.CATEGORY_OPERATION,
        action="announcement.delete",
        user=current_user,
        target_type="announcement",
        target_id=announcement_id,
        detail="删除公告",
    )
    return Response.success(message="已删除")
