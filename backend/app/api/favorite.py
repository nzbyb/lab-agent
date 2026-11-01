from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.services import favorite_service

router = APIRouter(prefix="/favorite", tags=["收藏与浏览记录"])

# 注意顺序：/ids、/list、/recent 必须写在 /{lab_id} 之前。
# FastAPI 按声明顺序匹配路由，写在后面的话 "ids" 会先被当成 lab_id 去转 int，
# 直接 422——而这个 422 看起来像参数错了，很难联想到是路由顺序。


@router.get("/ids")
def get_favorite_ids(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return Response.success(data=favorite_service.list_favorite_ids(db, current_user))


@router.get("/list")
def get_favorite_list(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return Response.success(data=favorite_service.list_favorites(db, current_user))


@router.get("/recent")
def get_recent_views(
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return Response.success(
        data=favorite_service.list_recent_views(db, current_user, limit)
    )


@router.post("/{lab_id}")
def add_favorite(
    lab_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    favorite_service.add_favorite(db, current_user, lab_id)
    return Response.success(message="已收藏")


@router.delete("/{lab_id}")
def remove_favorite(
    lab_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    favorite_service.remove_favorite(db, current_user, lab_id)
    return Response.success(message="已取消收藏")


@router.post("/{lab_id}/view")
def record_view(
    lab_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    favorite_service.record_view(db, current_user, lab_id)
    return Response.success()
