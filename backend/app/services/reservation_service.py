import asyncio
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime

from app.common.exceptions import BusinessException
from app.common.response import PageResponse
from app.database import SessionLocal, engine
from app.models.equipment import Equipment
from app.models.lab import Lab
from app.models.reservation import Reservation
from app.models.user import User
from app.schemas.reservation import (
    FreeSlotItem,
    FreeSlotResponse,
    ReservationCreateRequest,
    ReservationResponse,
    normalize_date,
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
    """某天算"占用"的预约：约设备时只跟同一台设备的预约比，约整个实验室时只跟实验室级预约比"""
    query = db.query(Reservation).filter(
        Reservation.date == date,
        Reservation.status.in_([0, 1]),
    )
    if equipment_id:
        # 设备分支不能再叠 lab_id。设备是能被改挂到别的实验室的
        # （equipment_service.update_equipment 直接按 payload 里的 lab_id 改），
        # 老预约记的还是旧 lab_id，再按 lab_id 过滤就看不见它了——
        # 同一台设备同一时段能被约两次。
        # equipment_id 全库唯一，单靠它就足以确定冲突范围。
        return query.filter(Reservation.equipment_id == equipment_id)
    # 实验室级预约按 lab_id 隔离，且只跟"整间实验室"的预约比。
    # 约实验室和约设备互不冲突，这是刻意的设计，别顺手改成一起比。
    return query.filter(
        Reservation.lab_id == lab_id,
        Reservation.equipment_id.is_(None),
    )


# 抢锁最多等多久（秒）。等不到说明同一时段正被大量并发抢占，直接让用户重试。
_BOOKING_LOCK_TIMEOUT = 5


def _booking_lock_name(lab_id: int, date: str, equipment_id: int | None) -> str:
    """同一天、同一个预约目标共用一个锁名。

    约整间实验室和约某台设备用不同的锁——它们在业务上互不冲突，
    没必要互相排队。0 是"整间实验室"的占位，因为锁名不能为空。

    锁名必须跟 _busy_query 的判定范围一一对应，否则会漏锁：
    设备那把锁只认 equipment_id（全库唯一），不能再带 lab_id，
    不然设备改挂实验室之后新旧两个锁名不同，两个请求各拿一把锁同时进来。
    实验室那把锁名保持原样：它的判定范围（lab_id + 日期）没变，
    名字本来就带 lab_id、跟 _busy_query 的实验室分支对得上，没有改的理由。
    """
    if equipment_id:
        return f"lab_agent:book:eq:{equipment_id}:{date}"
    return f"lab_agent:book:{lab_id}:{date}:0"


@contextmanager
def _booking_lock(lab_id: int, date: str, equipment_id: int | None):
    """把「查冲突 + 插入」串成临界区。

    没有这把锁时，两个请求可以同时查到"没有冲突"，然后双双插入成功，
    同一时段就出现两条预约。这里用 MySQL 的命名锁排掉这个窗口。

    锁是挂在连接上的。Session 一旦 commit 就会把连接还回连接池，
    再执行 RELEASE_LOCK 很可能落到另一条连接上，锁就永远留在原来那条连接里了。
    所以这里单独占用一条连接专职持锁，用完立刻释放并归还。
    """
    name = _booking_lock_name(lab_id, date, equipment_id)
    conn = engine.connect()
    try:
        acquired = conn.execute(
            text("SELECT GET_LOCK(:name, :timeout)"),
            {"name": name, "timeout": _BOOKING_LOCK_TIMEOUT},
        ).scalar()
        if acquired != 1:
            raise BusinessException(message="当前预约的人较多，请稍后重试")
        yield
    finally:
        conn.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": name})
        conn.close()


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
        # 设备必须属于所选实验室。不校验的话，把设备挂到别的 lab_id 下提交，
        # 这条占位记录会因为 _busy_query 的 lab_id 过滤而对正确的冲突查询隐身，
        # 同一台设备就能被两个人同时约走。
        if equipment.lab_id != data.lab_id:
            raise BusinessException(message="该设备不属于所选实验室")

    # 上面的校验查询已经开启了事务，MySQL 的 REPEATABLE READ 会在那一刻固定读快照。
    # 不先结束它，下面拿到锁之后读到的仍是旧数据，照样会漏掉别人刚提交的预约。
    user_id = current_user.id  # rollback 会过期 ORM 对象，先把要用的值取出来
    db.rollback()

    # 「查冲突」和「插入」之间必须互斥，否则两个并发请求会同时通过检查。
    # 用不到加锁的校验都放在临界区外面，减少排队时间。
    with _booking_lock(data.lab_id, data.date, data.equipment_id):
        # 同一实验室、同一天，已有"待审核/已通过"的预约与本次时间段重叠
        # 约设备时只跟同一台设备的预约比；约整个实验室时只跟实验室级预约比
        busy = _busy_query(db, data.lab_id, data.date, data.equipment_id).filter(
            Reservation.start_time < data.end_time,
            Reservation.end_time > data.start_time,
        )
        if busy.first():
            raise BusinessException(message="实验室已被预约")

        reservation_model = Reservation(
            user_id=user_id,
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
    # 这个函数只有 agent 工具在调，没有路由层的 schema 兜底，
    # date 是模型直接给的字符串，必须在这里自己规范化 + 校验。
    try:
        date = normalize_date(date)
    except ValueError:
        raise BusinessException(message="日期格式应为 YYYY-MM-DD")

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
        if equipment.lab_id != lab_id:
            raise BusinessException(message="该设备不属于所选实验室")

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
