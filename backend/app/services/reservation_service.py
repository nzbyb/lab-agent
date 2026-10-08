import asyncio

from sqlalchemy.orm import Session
from datetime import datetime

from app.common.exceptions import BusinessException
from app.common.response import PageResponse
from app.database import SessionLocal
from app.models.equipment import Equipment
from app.models.lab import Lab
from app.models.reservation import Reservation
from app.models.user import User
from app.schemas.reservation import (
    FreeSlotItem,
    FreeSlotResponse,
    ReservationCreateRequest,
    ReservationResponse,
)


def get_reservation_page_list(
    db: Session,
    current_user: User,
    page: int,
    page_size: int,
    status: int | None = None,
):
    query = db.query(Reservation)
    if current_user.role != "admin":
        query = query.filter(Reservation.user_id == current_user.id)
    if status is not None:
        query = query.filter(Reservation.status == status)
    total = query.count()
    items = (
        query.order_by(Reservation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    result = []
    for item in items:
        res = ReservationResponse.model_validate(item)
        res.user_name = item.user.name if item.user else None
        res.lab_name = item.lab.name if item.lab else None
        res.equipment_name = item.equipment.name if item.equipment else None
        res.type = "设备预约" if item.equipment_id else "实验室预约"
        result.append(res)
    return PageResponse(list=result, total=total)


def _busy_query(db: Session, lab_id: int, date: str, equipment_id: int | None):
    """某实验室某天算"占用"的预约：约设备时只跟同一台设备的预约比，约整个实验室时只跟实验室级预约比"""
    query = db.query(Reservation).filter(
        Reservation.lab_id == lab_id,
        Reservation.date == date,
        Reservation.status.in_([0, 1]),
    )
    if equipment_id:
        return query.filter(Reservation.equipment_id == equipment_id)
    return query.filter(Reservation.equipment_id.is_(None))


def create_reservation(db: Session, current_user: User, data: ReservationCreateRequest):
    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")
    if data.date < current_date:
        raise BusinessException(message="预约日期不能早于当前日期")
    if data.end_time < data.start_time:
        raise BusinessException(message="预约的结束时间不能早于开始时间")
    if data.date == current_date and data.start_time < current_time:
        raise BusinessException(message="预约的开始时间不能早于当前时间")

    lab = db.query(Lab).filter(Lab.id == data.lab_id).first()
    if not lab:
        raise BusinessException(message="实验室不存在")
    if lab.status != 1:
        raise BusinessException(message="实验室未开放预约")
    if lab.open_time and data.start_time < lab.open_time:
        raise BusinessException(message="预约的开始时间不能早于实验室开放时间")
    if lab.close_time and data.end_time > lab.close_time:
        raise BusinessException(message="预约的结束时间不能晚于实验室关闭时间")

    if data.equipment_id:
        equipment = (
            db.query(Equipment).filter(Equipment.id == data.equipment_id).first()
        )
        if not equipment:
            raise BusinessException(message="实验室设备不存在")
        if equipment.status != 1:
            raise BusinessException(message="实验室设备正在维修")

    # 同一实验室、同一天，已有"待审核/已通过"的预约与本次时间段重叠
    # 约设备时只跟同一台设备的预约比；约整个实验室时只跟实验室级预约比
    busy = _busy_query(db, data.lab_id, data.date, data.equipment_id).filter(
        Reservation.start_time < data.end_time,
        Reservation.end_time > data.start_time,
    )
    if busy.first():
        raise BusinessException(message="实验室已被预约")

    reservation_model = Reservation(
        user_id=current_user.id,
        lab_id=data.lab_id,
        equipment_id=data.equipment_id,
        date=data.date,
        start_time=data.start_time,
        end_time=data.end_time,
        remark=data.remark,
        status=0,
    )
    db.add(reservation_model)
    db.commit()


def get_free_slots(
    db: Session, lab_id: int, date: str, equipment_id: int | None = None
):
    """某实验室（或某台设备）某天的空闲时段 = 开放时间 减去 已被占用的时间段"""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    if date < today:
        raise BusinessException(message="不能查询过去的日期")

    lab = db.query(Lab).filter(Lab.id == lab_id).first()
    if not lab:
        raise BusinessException(message="实验室不存在")
    if lab.status != 1:
        raise BusinessException(message="实验室未开放预约")

    equipment = None
    if equipment_id:
        equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
        if not equipment:
            raise BusinessException(message="实验室设备不存在")
        if equipment.status != 1:
            raise BusinessException(message="实验室设备正在维修")

    open_time = lab.open_time or "00:00"
    close_time = lab.close_time or "23:59"
    cursor = open_time
    # 查的是今天的话，已经过去的时间不算空闲
    if date == today:
        cursor = max(cursor, now.strftime("%H:%M"))

    busy = sorted(
        (item.start_time, item.end_time)
        for item in _busy_query(db, lab_id, date, equipment_id).all()
    )

    slots = []
    for busy_start, busy_end in busy:
        if busy_end > cursor:
            if busy_start > cursor:
                slots.append((cursor, min(busy_start, close_time)))
            cursor = max(cursor, busy_end)
        if cursor >= close_time:
            break
    if cursor < close_time:
        slots.append((cursor, close_time))

    return FreeSlotResponse(
        lab_id=lab.id,
        lab_name=lab.name,
        equipment_id=equipment_id,
        equipment_name=equipment.name if equipment else None,
        date=date,
        open_time=open_time,
        close_time=close_time,
        slots=[
            FreeSlotItem(start_time=start, end_time=end)
            for start, end in slots
            if end > start
        ],
        busy=[FreeSlotItem(start_time=start, end_time=end) for start, end in busy],
    )


def cancel_reservation(db: Session, current_user: User, reservation_id: int):
    item = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not item:
        raise BusinessException(message="预约记录不存在")
    if item.user_id != current_user.id:
        raise BusinessException(message="无权限取消该预约", code=403)
    if item.status != 0:
        raise BusinessException(message="只有待审核的预约才能取消")
    item.status = 3
    db.commit()


def audit_reservation(db: Session, reservation_id: int, status: int):
    if status not in [1, 2]:
        raise BusinessException(message="审核状态不合法")
    item = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not item:
        raise BusinessException(message="预约记录不存在")
    if item.status != 0:
        raise BusinessException(message="当前状态不支持审核")
    item.status = status
    db.commit()


def expire_pending_reservations():
    db = SessionLocal()
    try:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        time = now.strftime("%H:%M")
        items = db.query(Reservation).filter(Reservation.status == 0).all()
        changed = False
        for item in items:
            if item.date < today or (item.date == today and item.end_time <= time):
                item.status = 3
                changed = True
        if changed:
            db.commit()

    finally:
        db.close()


async def run_expire_scan():
    try:
        while True:
            await asyncio.to_thread(expire_pending_reservations)
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        return
