from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.common.response import Response
from app.models.user import User
from app.dependencies.auth import get_current_user, get_current_admin
from app.schemas.user import UserUpdateRequest, UserCreateRequest
from app.services import user_service
from app.database import get_db
from app.schemas.user import AdminPasswordResetRequest, PasswordUpdateRequest

router = APIRouter(prefix="/user", tags=["用户信息接口"])


@router.get("/me")
def get_user_info(current_user: User = Depends(get_current_user)):
    return Response.success(data=user_service.get_user_info(current_user))


@router.put("/me")
def update_user_info(
    data: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    res = user_service.update_user_info(db, current_user, data)
    return Response.success(data=res)


@router.put("/password")
def update_password(
    data: PasswordUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_service.update_password(db, current_user, data)
    return Response.success()


@router.get("/list")
def get_user_list(
    page: int = Query(1, ge=1),
    # 上界不能省：page_size 会直接进 LIMIT，传个几百万就是一次全表读。
    page_size: int = Query(10, ge=1, le=100),
    keywords: str | None = None,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    res = user_service.get_user_page_list(db, page, page_size, keywords)
    return Response.success(data=res)


@router.post("")
def create_user(
    data: UserCreateRequest,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    res = user_service.create_user(db, data)
    return Response.success(data=res)


@router.put("/{user_id}")
def create_user(
    user_id: int,
    data: UserUpdateRequest,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    res = user_service.update_user(db, user_id, data)
    return Response.success(data=res)


@router.delete("/{user_id}")
def create_user(
    user_id: int,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    res = user_service.delete_user(db, user_id, current_user)
    return Response.success()


# 路径里有 /{user_id}/password，比 /{user_id} 多一段，两者不会互相截胡，
# 所以这条不像上面 /password 那样非得抢在 /{user_id} 前面声明。
#
# 它和被放在 /me 那组的 PUT /password 是两条不同的路：
# 那条是本人改密码（要原密码），这条是管理员重置他人密码（不要原密码，
# 权限由 get_current_admin 兜住）。
@router.put("/{user_id}/password")
def reset_user_password(
    user_id: int,
    data: AdminPasswordResetRequest,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user_service.reset_password(db, user_id, data)
    return Response.success(message="密码已重置")
