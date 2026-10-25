from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_admin, get_current_user
from app.models.user import User
from app.schemas.reservation import (
    AuditReservationRequest,
    ForceCancelRequest,
    ReservationCreateRequest,
)
from app.services import reservation_service

router = APIRouter(prefix="/reservation", tags=["预约相关接口"])


@router.get("/list")
def get_reservation_page_list(
    page: int = Query(1, ge=1),
    # 上界不能省：page_size 会直接进 LIMIT，传个几百万就是一次全表读。
    page_size: int = Query(10, ge=1, le=100),
    status: int | None = None,
    # 日期筛选：两端都是可选，只传一边就是"从这天起 / 到这天为止"。
    # 格式校验和先后顺序在 service 里做，那里还能顺手给出能看懂的提示。
    date_from: str | None = None,
    date_to: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    res = reservation_service.get_reservation_page_list(
        db, current_user, page, page_size, status, date_from, date_to
    )
    return Response.success(data=res)


@router.get("/week-schedule")
def get_week_schedule(
    lab_id: int = Query(..., ge=1),
    # 起始日期。不传就从今天开始；传了也允许是过去的周（只读查看，不用于下单）。
    week_start: str | None = None,
    equipment_id: int | None = Query(None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 放在 /{reservation_id} 这类路径参数路由之前也没关系：这里是 GET 且路径固定，
    # FastAPI 会按声明顺序匹配，而 reservation_id 的路由都是 PUT，不会撞。
    res = reservation_service.get_week_schedule(
        db, lab_id, week_start, equipment_id
    )
    return Response.success(data=res)


@router.post("")
def create_reservation(
    data: ReservationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reservation_service.create_reservation(db, current_user, data)
    return Response.success()


@router.put("/{reservation_id}/cancel")
def cancel_reservation(
    reservation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reservation_service.cancel_reservation(db, current_user, reservation_id)
    return Response.success()


@router.put("/{reservation_id}/audit")
def audit_reservation(
    reservation_id: int,
    data: AuditReservationRequest,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    reservation_service.audit_reservation(db, reservation_id, data.status)
    return Response.success()


@router.put("/{reservation_id}/force-cancel")
def force_cancel_reservation(
    reservation_id: int,
    data: ForceCancelRequest,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    reservation_service.force_cancel_reservation(db, reservation_id, data.reason)
    return Response.success(message="预约已强制取消")
