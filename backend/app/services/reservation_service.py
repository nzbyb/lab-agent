import asyncio
from contextlib import contextmanager

from sqlalchemy import and_, or_, text
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timedelta

from app.common.exceptions import BusinessException
from app.common.response import PageResponse
from app.config import settings
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
    ScheduleDay,
    WeekScheduleResponse,
    normalize_date,
)
# 开放时段按周中/周末分两套，"某一天该用哪套"只在 lab_service 里判断，
# 这里和 agent 工具都从它派生，不再各自读 lab.open_time。
from app.services import lab_service, notification_service

# 超时自动取消的原因文案。统计里也按这句话认"自动取消"，别处不要再手写一份。
AUTO_CANCEL_REASON = "超时未审核，系统自动取消"


def _reservation_summary(item: Reservation) -> str:
    """给消息用的一句话摘要。

    实验室名和日期时段都写进去，用户不用点回预约列表猜是哪一条。
    设备预约再补上设备名，否则同一间实验室约了整间和约了设备的两条消息
    看起来一模一样。
    """
    lab_name = item.lab.name if item.lab else f"实验室#{item.lab_id}"
    if item.equipment_id and item.equipment:
        subject = f"{lab_name}的{item.equipment.name}"
    else:
        subject = lab_name
    return f"{subject}（{item.date} {item.start_time}-{item.end_time}）"


def _start_at(item: Reservation) -> datetime | None:
    """把预约的日期 + 开始时间拼成一个可比较的时刻。

    库里这两列都是字符串（分别补零到 YYYY-MM-DD / HH:MM），拼起来再解析一次
    比四处手写字符串切片安全。历史数据格式不对时返回 None，调用方按"无法判断"
    处理——宁可不让取消，也不能因为解析失败就放行。
    """
    try:
        return datetime.strptime(f"{item.date} {item.start_time}", "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None


def _can_cancel(item: Reservation, current_user: User, now: datetime) -> bool:
    """这一行对当前用户来能不能自行取消。

    规则跟 cancel_reservation 完全一致，两处必须一起改，否则会出现
    "按钮是亮的，点下去被拒"或者反过来"能取消却看不见按钮"。
    """
    if item.user_id != current_user.id:
        return False
    if item.status == 0:
        return True
    if item.status == 1:
        start = _start_at(item)
        if start is None:
            return False
        return start - now >= timedelta(
            hours=settings.RESERVATION_CANCEL_DEADLINE_HOURS
        )
    return False


def get_reservation_page_list(
    db: Session,
    current_user: User,
    page: int,
    page_size: int,
    status: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
):
    # 日期筛选走的是 reservation.date 这一列（YYYY-MM-DD 字符串），
    # 必须先规范化再比大小，否则 "2026-10-9" 会被排到 "2026-10-10" 后面。
    if date_from:
        try:
            date_from = normalize_date(date_from)
        except ValueError as exc:
            raise BusinessException(message="开始日期格式应为 YYYY-MM-DD") from exc
    if date_to:
        try:
            date_to = normalize_date(date_to)
        except ValueError as exc:
            raise BusinessException(message="结束日期格式应为 YYYY-MM-DD") from exc
    if date_from and date_to and date_from > date_to:
        raise BusinessException(message="开始日期不能晚于结束日期")

    query = db.query(Reservation)
    if current_user.role != "admin":
        query = query.filter(Reservation.user_id == current_user.id)
    if status is not None:
        query = query.filter(Reservation.status == status)
    if date_from:
        query = query.filter(Reservation.date >= date_from)
    if date_to:
        query = query.filter(Reservation.date <= date_to)

    total = query.count()
    items = (
        query.order_by(Reservation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    now = datetime.now()
    result = []
    for item in items:
        res = ReservationResponse.model_validate(item)
        res.user_name = item.user.name if item.user else None
        res.lab_name = item.lab.name if item.lab else None
        res.equipment_name = item.equipment.name if item.equipment else None
        res.type = "设备预约" if item.equipment_id else "实验室预约"
        res.can_cancel = _can_cancel(item, current_user, now)
        result.append(res)
    return PageResponse(list=result, total=total)


def _busy_query(db: Session, lab_id: int, date: str, equipment_id: int | None):
    """某天算"占用"的预约。

    **实验室和设备共用同一份占用**（2026-10 改的；在此之前两边各算各的，
    约了设备不影响约整间实验室，反过来也一样）：

      - 约整间实验室：这间实验室当天**全部**预约都算占用，包括各台设备各自的预约。
        一间实验室只有一个场地，里面的设备被人约走了，整间就不该再对外约。
      - 约某台设备：只算「这台设备自己的预约」+「整间实验室的预约」。
        同一间实验室里**另一台**设备被约走不算冲突——否则约走一台设备就等于占掉整间，
        设备预约这件事本身就没意义了。

    改这条规则时**必须连着 _booking_lock_name 一起改**，两边范围对不上就会漏锁。
    """
    query = db.query(Reservation).filter(
        Reservation.date == date,
        Reservation.status.in_([0, 1]),
    )
    if equipment_id:
        # 「这台设备」那条不能再叠 lab_id：设备是能被改挂到别的实验室的
        # （equipment_service.update_equipment 直接按 payload 里的 lab_id 改），
        # 老预约记的还是旧 lab_id，再按 lab_id 过滤就看不见它了——
        # 同一台设备同一时段能被约两次。
        # equipment_id 全库唯一，单靠它就足以确定这台设备的占用范围。
        return query.filter(
            or_(
                Reservation.equipment_id == equipment_id,
                and_(
                    Reservation.lab_id == lab_id,
                    Reservation.equipment_id.is_(None),
                ),
            )
        )
    # 整间实验室这条按 lab_id 认，连它下面各台设备的预约一起算。
    #
    # 已知的窄口子：设备被改挂到别的实验室之后，**改挂之前**那条预约记的还是旧
    # lab_id，按新 lab_id 查就看不见它，此时段整间实验室会被放行，而那台设备现在
    # 其实就摆在这间实验室里。要堵得把 equipment 表一起 join 进来，代价和收益不成
    # 比例（得先有人搬设备、再有同期预约才会碰到），先记在这儿。
    return query.filter(Reservation.lab_id == lab_id)


# 抢锁最多等多久（秒）。等不到说明同一时段正被大量并发抢占，直接让用户重试。
_BOOKING_LOCK_TIMEOUT = 5


def _booking_lock_name(lab_id: int, date: str) -> str:
    """同一天、同一间实验室共用一个锁名。

    锁名必须跟 _busy_query 的判定范围一一对应，否则会漏锁。
    以前这里按「整间实验室」和「每台设备」各发一把锁，那是因为当时两者互不冲突；
    现在约整间和约设备会互相挡，就必须合并成一把——不然「约整间」和「约某台设备」
    的两个请求各拿一把锁、各查各的，都说没冲突，然后双双插入成功。

    合并之后同一间实验室里两台不同设备的预约也会互相排一下队。临界区只有
    「查一次 + 插一条」，是毫秒级的，换来的是不用再论证两把锁的加锁顺序。
    """
    return f"lab_agent:book:{lab_id}:{date}"


@contextmanager
def _booking_lock(lab_id: int, date: str):
    """把「查冲突 + 插入」串成临界区。

    没有这把锁时，两个请求可以同时查到"没有冲突"，然后双双插入成功，
    同一时段就出现两条预约。这里用 MySQL 的命名锁排掉这个窗口。

    锁是挂在连接上的。Session 一旦 commit 就会把连接还回连接池，
    再执行 RELEASE_LOCK 很可能落到另一条连接上，锁就永远留在原来那条连接里了。
    所以这里单独占用一条连接专职持锁，用完立刻释放并归还。
    """
    name = _booking_lock_name(lab_id, date)
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
    # 周中和周末是两套时段，用预约的那一天去取（date 已由 schema 规范化成 YYYY-MM-DD）。
    day_open, day_close = lab_service.resolve_open_hours(lab, data.date)
    if day_open is None:
        # 这一天的时段压根没设。以前这种情况是"没有限制、随便约"，
        # 现在统一成"当天不开放"——时段既然按天分叉，"没设"就必须有个明确含义，
        # 而"随便约"跟上面那条"要管理员启用才能约"本来就是矛盾的。
        raise BusinessException(message="该实验室当天不开放")
    if data.start_time < day_open:
        raise BusinessException(message="预约的开始时间不能早于实验室开放时间")
    if data.end_time > day_close:
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
    with _booking_lock(data.lab_id, data.date):
        # 同一实验室、同一天，已有"待审核/已通过"的预约与本次时间段重叠就算占用。
        # 占用范围（整间实验室 / 某台设备 / 两者互相影响）全在 _busy_query 里定。
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

    # 这一天的时段（周中/周末两套，date 已规范化）。注意这个判断要留在设备归属校验**之后**：
    # 报"某台设备不属于这个实验室"比报"当天不开放"更贴近用户实际搞错的地方。
    #
    # 以前这里写的是 `lab.open_time or "00:00"`——没设时段就等于全天都能约，
    # 于是校验那边拦得住、空闲查询这边却列出一整天。现在两头统一：没设就是当天不开放。
    open_time, close_time = lab_service.resolve_open_hours(lab, date)
    if open_time is None:
        raise BusinessException(message="该实验室当天不开放")
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


def get_week_schedule(
    db: Session,
    lab_id: int,
    start_date: str | None = None,
    equipment_id: int | None = None,
) -> WeekScheduleResponse:
    """从 start_date 起连续 7 天的开放时段和已占用时段。

    界面上的「一周 × 时段」网格就靠这一份数据。和 get_free_slots 的区别是
    它一次给出多天、只给原始占用，不在这里算空闲区间——留空还是占用、
    是不是已经过去，都由前端拿同一份 busy/open_time 判断，避免两边各推一套
    时段切分规则，出现"网格说能点、下单说没空"。
    """
    if start_date:
        try:
            start = datetime.strptime(normalize_date(start_date), "%Y-%m-%d")
        except ValueError:
            raise BusinessException(message="日期格式应为 YYYY-MM-DD")
    else:
        # 默认从今天开始。不把时间部分带进来，后面加天数才不会错位。
        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

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

    days: list[ScheduleDay] = []
    for offset in range(7):
        day = start + timedelta(days=offset)
        date_str = day.strftime("%Y-%m-%d")
        open_time, close_time = lab_service.resolve_open_hours(lab, date_str)
        busy: list[FreeSlotItem] = []
        if open_time is not None:
            # 占用范围和 create_reservation 用的是同一个 _busy_query：
            # 整间实验室会显示所有设备预约，单台设备只显示自己和整间实验室的预约。
            busy = [
                FreeSlotItem(start_time=start_time, end_time=end_time)
                for start_time, end_time in sorted(
                    (item.start_time, item.end_time)
                    for item in _busy_query(db, lab_id, date_str, equipment_id).all()
                )
            ]
        days.append(
            ScheduleDay(
                date=date_str,
                weekday=day.weekday(),
                open_time=open_time,
                close_time=close_time,
                busy=busy,
            )
        )

    return WeekScheduleResponse(
        lab_id=lab.id,
        lab_name=lab.name,
        equipment_id=equipment_id,
        equipment_name=equipment.name if equipment else None,
        start_date=start.strftime("%Y-%m-%d"),
        days=days,
    )


def cancel_reservation(db: Session, current_user: User, reservation_id: int):
    """本人取消预约。

    - 待审核：随时可以取消。
    - 已通过：只在开始前 N 小时以上能取消（N 见 RESERVATION_CANCEL_DEADLINE_HOURS）。
      再近就锁住，让用户去找管理员——管理员那条"强制取消"带原因，
      用户那边看得到是为什么没的。
    - 已拒绝 / 已取消：没有可取消的东西。
    """
    item = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not item:
        raise BusinessException(message="预约记录不存在")
    if item.user_id != current_user.id:
        raise BusinessException(message="无权限取消该预约", code=403)

    now = datetime.now()
    if item.status == 1:
        start = _start_at(item)
        deadline = timedelta(hours=settings.RESERVATION_CANCEL_DEADLINE_HOURS)
        if start is None or start - now < deadline:
            raise BusinessException(
                message=(
                    f"预约开始前 {settings.RESERVATION_CANCEL_DEADLINE_HOURS} "
                    "小时内不能自行取消，请联系管理员"
                )
            )
    elif item.status != 0:
        raise BusinessException(message="当前状态的预约不能取消")

    item.status = 3
    item.cancel_time = now
    # 本人取消不填原因：是谁取消的已经由"操作人就是预约人"确定了，
    # 再写一句"用户取消"只是噪音。管理员强制取消才必须有原因。
    item.cancel_reason = None
    db.commit()


def force_cancel_reservation(
    db: Session, reservation_id: int, reason: str
) -> None:
    """管理员强制取消。待审核和已通过都能取消，原因会留给用户看。

    这里刻意不复用 cancel_reservation：那条要校验归属、还要卡 2 小时截止线，
    管理员恰恰是为了越过这两条才来的。把两条路合并，迟早会有人给管理员也
    加上"开始前 2 小时内不能取消"。
    """
    item = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not item:
        raise BusinessException(message="预约记录不存在")
    if item.status not in (0, 1):
        raise BusinessException(message="当前状态的预约不能取消")

    now = datetime.now()
    item.status = 3
    item.cancel_time = now
    item.cancel_reason = reason
    summary = _reservation_summary(item)
    notification = notification_service.create_notification(
        db,
        user_id=item.user_id,
        type=notification_service.TYPE_FORCE_CANCELED,
        title="预约已被取消",
        content=f"你预约的 {summary} 已被管理员取消。原因：{reason}。",
        reservation_id=item.id,
    )
    # flush 只为拿到消息主键：邮件在 commit 之后才发，那时事务已经结束，
    # 不能再依赖 ORM 对象上还没刷新的 id。消息和预约状态仍然在同一个事务里。
    db.flush()
    notification_id = notification.id
    db.commit()
    notification_service.dispatch_email(notification_id)


def audit_reservation(db: Session, reservation_id: int, status: int):
    if status not in [1, 2]:
        raise BusinessException(message="审核状态不合法")
    item = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not item:
        raise BusinessException(message="预约记录不存在")
    if item.status != 0:
        raise BusinessException(message="当前状态不支持审核")

    item.status = status
    item.audit_time = datetime.now()
    summary = _reservation_summary(item)
    if status == 1:
        type_ = notification_service.TYPE_APPROVED
        title = "预约已通过"
        content = f"你预约的 {summary} 已通过审核，请按时使用。"
    else:
        type_ = notification_service.TYPE_REJECTED
        title = "预约被拒绝"
        content = f"你预约的 {summary} 未通过审核。如需了解原因，请联系管理员。"

    notification = notification_service.create_notification(
        db,
        user_id=item.user_id,
        type=type_,
        title=title,
        content=content,
        reservation_id=item.id,
    )
    db.flush()
    notification_id = notification.id
    db.commit()
    notification_service.dispatch_email(notification_id)


def expire_pending_reservations():
    db = SessionLocal()
    try:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        time = now.strftime("%H:%M")
        # 一次把实验室和设备带出来：下面拼消息摘要要读名字，
        # 不 joinedload 就是每条预约各查一次（N+1）。
        items = (
            db.query(Reservation)
            .options(
                joinedload(Reservation.lab), joinedload(Reservation.equipment)
            )
            .filter(Reservation.status == 0)
            .all()
        )
        notifications = []
        for item in items:
            if item.date < today or (item.date == today and item.end_time <= time):
                item.status = 3
                item.cancel_time = now
                # 自动取消也要写原因：否则用户只看到"已取消"，会以为是管理员
                # 动的手，转头去问人。写清楚是系统超时，省一轮扯皮。
                item.cancel_reason = AUTO_CANCEL_REASON
                summary = _reservation_summary(item)
                notifications.append(
                    notification_service.create_notification(
                        db,
                        user_id=item.user_id,
                        type=notification_service.TYPE_AUTO_CANCELED,
                        title="预约已自动取消",
                        content=(
                            f"你预约的 {summary} 因超时未审核，已被系统自动取消，"
                            "请重新预约或联系管理员。"
                        ),
                        reservation_id=item.id,
                    )
                )
        if notifications:
            db.flush()
            notification_ids = [item.id for item in notifications]
            db.commit()
            for notification_id in notification_ids:
                notification_service.dispatch_email(notification_id)

    finally:
        db.close()


async def run_expire_scan():
    try:
        while True:
            await asyncio.to_thread(expire_pending_reservations)
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        return
