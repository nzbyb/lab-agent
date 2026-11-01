from datetime import datetime, time, timedelta
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.common.exceptions import BusinessException
from app.models.equipment import Equipment
from app.models.lab import Lab
from app.models.reservation import Reservation
from app.models.user import User
from app.schemas.statistics import (
    AdminWorkbenchResponse,
    LabRankItem,
    PendingReservationItem,
    StatisticsOverviewResponse,
    TrendPoint,
)
from app.services.reservation_service import AUTO_CANCEL_REASON

# 趋势窗口长度（含今天）。改它要连着 tests/test_statistics.py 里断言长度的用例一起改。
_TREND_DAYS = 7
# 排行榜取前几名
_RANKING_LIMIT = 5


def _reservation_scope(db: Session, current_user: User):
    """预约类指标的取数范围。

    口径与 reservation_service.get_reservation_page_list 里那句 `role != "admin"` 完全一致：
    只有管理员看全库，其余角色只看自己的。前端 stores/user.js 的 reservationCountLabel
    用的是同一个判据，那两处文案和这里的数字必须一起改，否则管理员会把全库总数当成自己的。
    """
    query = db.query(Reservation)
    if current_user.role != "admin":
        query = query.filter(Reservation.user_id == current_user.id)
    return query


def _as_day(value) -> str:
    """把 func.date() 的返回值归一成补零的 YYYY-MM-DD。

    pymysql 下它可能返回 date 对象、也可能返回字符串，不归一的话拿去当 dict 的 key 会对不上，
    表现为"每一天都被补成 0"——图是空的，但没有任何报错。
    """
    return value.strftime("%Y-%m-%d") if hasattr(value, "strftime") else str(value)


def _get_reservation_trend(scope_query) -> list[TrendPoint]:
    """近 _TREND_DAYS 天每天**新提交**的预约数，按 create_time 分组。

    这里刻意用 create_time 而不是 Reservation.date，两者是不同的指标：
    - create_time = 下单时间，答的是"最近每天产生了多少预约"
    - date = 预约哪天来用（目标日期），答的是"这些日期各被约了多少次"
    另外 date 是 String(20)，按天分组只能靠字典序，依赖"已补零"这个前提；create_time 是
    真 DateTime 列，分组干净，窗口也天然指向过去。

    没有预约的那几天由**服务端**补 0：接口返回的数组自洽（长度恒为 _TREND_DAYS、日期连续），
    前端拿到的就是可以直接画的稠密序列，测试也能直接断言长度和连续性。
    """
    # naive 本地时间，与 Base.create_time 的 default=datetime.now 同源。
    # 换成 UTC 会让整个窗口错位一天。
    today = datetime.now().date()
    start_day = today - timedelta(days=_TREND_DAYS - 1)
    start_dt = datetime.combine(start_day, time.min)

    rows = (
        scope_query.with_entities(
            func.date(Reservation.create_time), func.count(Reservation.id)
        )
        .filter(Reservation.create_time >= start_dt)
        .group_by(func.date(Reservation.create_time))
        .all()
    )
    counted = {_as_day(day): count for day, count in rows}

    trend = []
    for offset in range(_TREND_DAYS):
        key = (start_day + timedelta(days=offset)).strftime("%Y-%m-%d")
        trend.append(TrendPoint(date=key, count=counted.get(key, 0)))
    return trend


def _get_lab_ranking(db: Session, scope_query) -> list[LabRankItem]:
    """预约数最多的前 _RANKING_LIMIT 个实验室。

    只算"有效预约"（status in (0, 1)），口径对齐 reservation_service._busy_query：
    已拒绝(2)和已取消(3)不该进排行榜。
    """
    rows = (
        scope_query.with_entities(
            Reservation.lab_id, func.count(Reservation.id).label("cnt")
        )
        .filter(Reservation.status.in_([0, 1]))
        .group_by(Reservation.lab_id)
        # 平手时按 lab_id 升序兜底。少了这个 tie-break，同分实验室的先后由数据库决定，
        # 同一个请求跑两次可能给出不同顺序，测试也会 flaky。
        .order_by(func.count(Reservation.id).desc(), Reservation.lab_id.asc())
        .limit(_RANKING_LIMIT)
        .all()
    )
    if not rows:
        return []

    # 名字一次批量取回来，不要在循环里逐个查（N+1）
    lab_ids = [lab_id for lab_id, _ in rows]
    names = dict(db.query(Lab.id, Lab.name).filter(Lab.id.in_(lab_ids)).all())

    return [
        LabRankItem(
            lab_id=lab_id,
            # 实验室被删过就查不到名字，给个还能看的兜底，别让接口整个挂掉
            lab_name=names.get(lab_id, f"实验室#{lab_id}"),
            count=count,
        )
        for lab_id, count in rows
    ]


def get_overview(db: Session, current_user: User) -> StatisticsOverviewResponse:
    """首页统计概览。

    所有指标都从现有 4 张表现算，**不需要新表、新列**——这点很重要：
    表结构由 Alembic 管（见 app/database.py 的 run_migrations），加一列就得配一条迁移，
    不是改完模型就完事。能不加列就不加。
    """
    scope_query = _reservation_scope(db, current_user)

    # 预约总数与四个状态计数用一条 group_by 拿全，不为每个状态各发一次 count。
    # 这里**不按状态过滤**：要的就是全量分桶。
    status_rows = (
        scope_query.with_entities(Reservation.status, func.count(Reservation.id))
        .group_by(Reservation.status)
        .all()
    )
    by_status = {status: count for status, count in status_rows}

    return StatisticsOverviewResponse(
        # 实验室与设备是全局资源，不按角色过滤（只有预约类指标分角色）
        lab_total=db.query(Lab).count(),
        lab_open_total=db.query(Lab).filter(Lab.status == 1).count(),
        equipment_total=db.query(Equipment).count(),
        equipment_normal_total=db.query(Equipment).filter(Equipment.status == 1).count(),
        equipment_repair_total=db.query(Equipment).filter(Equipment.status == 0).count(),
        reservation_total=sum(by_status.values()),
        # 状态语义见 models/reservation.py：0 待审核, 1 已通过, 2 已拒绝, 3 已取消
        reservation_pending_total=by_status.get(0, 0),
        reservation_approved_total=by_status.get(1, 0),
        reservation_rejected_total=by_status.get(2, 0),
        reservation_canceled_total=by_status.get(3, 0),
        reservation_trend=_get_reservation_trend(scope_query),
        lab_ranking=_get_lab_ranking(db, scope_query),
    )


def get_admin_workbench(db: Session) -> AdminWorkbenchResponse:
    """管理端首页的待办数字 + 等得最久的几条待审核。

    只给管理员看，所以这里**不按用户过滤**，和 get_overview 的 scope_query 不同。
    "今日预约"只算待审核和已通过：已拒绝 / 已取消的名额当天不会有人来用，
    算进去会让管理员以为今天很忙。
    """
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    cutoff = now - timedelta(days=7)

    pending_total = (
        db.query(Reservation).filter(Reservation.status == 0).count()
    )
    today_total = (
        db.query(Reservation)
        .filter(Reservation.date == today, Reservation.status.in_([0, 1]))
        .count()
    )
    today_pending_total = (
        db.query(Reservation)
        .filter(Reservation.date == today, Reservation.status == 0)
        .count()
    )
    auto_canceled_7d = (
        db.query(Reservation)
        .filter(
            Reservation.status == 3,
            Reservation.cancel_reason == AUTO_CANCEL_REASON,
            Reservation.cancel_time >= cutoff,
        )
        .count()
    )

    # 先提交的先处理，别让一条上周的申请一直压在最底下。
    # id 是 tie-break：同一秒提交的两条，顺序不能由数据库心情决定。
    rows = (
        db.query(Reservation)
        .filter(Reservation.status == 0)
        .order_by(Reservation.create_time.asc(), Reservation.id.asc())
        .limit(5)
        .all()
    )
    return AdminWorkbenchResponse(
        pending_total=pending_total,
        today_total=today_total,
        today_pending_total=today_pending_total,
        auto_canceled_7d=auto_canceled_7d,
        pending_list=[
            PendingReservationItem(
                id=item.id,
                user_name=item.user.name if item.user else None,
                lab_name=item.lab.name if item.lab else None,
                equipment_name=item.equipment.name if item.equipment else None,
                date=item.date,
                start_time=item.start_time,
                end_time=item.end_time,
                create_time=item.create_time,
            )
            for item in rows
        ],
    )


# ---------------------------------------------------------------------------
# 报表导出
# ---------------------------------------------------------------------------

# 一次最多导这么多行。超了直接报错而不是悄悄截断：截断的报表看起来"就是这些"，
# 拿去做统计会得出错误结论，比导不出来更糟。
_EXPORT_LIMIT = 10000

_STATUS_TEXT = {0: "待审核", 1: "已通过", 2: "已拒绝", 3: "已取消"}

_EXPORT_HEADERS = [
    ("预约ID", 10),
    ("预约人", 14),
    ("账号", 16),
    ("实验室", 20),
    ("设备", 18),
    ("预约日期", 14),
    ("开始时间", 10),
    ("结束时间", 10),
    ("状态", 10),
    ("备注", 30),
    ("提交时间", 20),
    ("审核时间", 20),
    ("取消时间", 20),
    ("取消原因", 30),
]


def _normalize_export_date(value: str | None, label: str) -> str | None:
    """校验并补零。date 列是字符串，比较全靠格式统一。"""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise BusinessException(message=f"{label}格式应为 YYYY-MM-DD")


def _fmt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else ""


def export_reservations(
    db: Session,
    date_from: str | None = None,
    date_to: str | None = None,
    status: int | None = None,
) -> tuple[bytes, str]:
    """导出预约明细，返回 (文件内容, 文件名)。

    筛的是 Reservation.date（用户来用的那天），不是提交时间——管理员做周报时
    关心的是"这周各天来了多少人"，跟哪天点的预约无关。
    """
    start = _normalize_export_date(date_from, "开始日期")
    end = _normalize_export_date(date_to, "结束日期")
    if start and end and start > end:
        raise BusinessException(message="开始日期不能晚于结束日期")

    query = db.query(Reservation).options(
        # 一次把关联表带出来，避免逐行查 user/lab/equipment（N+1）
        joinedload(Reservation.user),
        joinedload(Reservation.lab),
        joinedload(Reservation.equipment),
    )
    if start:
        query = query.filter(Reservation.date >= start)
    if end:
        query = query.filter(Reservation.date <= end)
    if status is not None:
        query = query.filter(Reservation.status == status)

    total = query.count()
    if total > _EXPORT_LIMIT:
        raise BusinessException(
            message=f"符合条件的预约有 {total} 条，超过单次导出上限 {_EXPORT_LIMIT} 条，请缩小日期范围"
        )

    items = query.order_by(
        Reservation.date.asc(),
        Reservation.start_time.asc(),
        # 同一天的同一时刻可能有多条，用 id 兜底，导两次顺序才一致
        Reservation.id.asc(),
    ).all()

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "预约明细"
    sheet.append([header for header, _ in _EXPORT_HEADERS])

    header_font = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="DDEBF7")
    for cell in sheet[1]:
        cell.font = header_font
        cell.fill = header_fill
    for index, (_, width) in enumerate(_EXPORT_HEADERS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    # 表头冻结：几千行往下翻时还知道每一列是什么
    sheet.freeze_panes = "A2"

    for item in items:
        sheet.append(
            [
                item.id,
                (item.user.name or item.user.username) if item.user else "",
                item.user.username if item.user else "",
                item.lab.name if item.lab else "",
                item.equipment.name if item.equipment else "",
                item.date,
                item.start_time,
                item.end_time,
                _STATUS_TEXT.get(item.status, str(item.status)),
                item.remark or "",
                _fmt(item.create_time),
                _fmt(item.audit_time),
                _fmt(item.cancel_time),
                item.cancel_reason or "",
            ]
        )

    summary = workbook.create_sheet("汇总")
    summary.append(["状态", "数量"])
    for cell in summary[1]:
        cell.font = header_font
        cell.fill = header_fill
    summary.column_dimensions["A"].width = 12
    summary.column_dimensions["B"].width = 10
    counts = {}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    for code in (0, 1, 2, 3):
        summary.append([_STATUS_TEXT[code], counts.get(code, 0)])
    summary.append(["合计", len(items)])

    buffer = BytesIO()
    workbook.save(buffer)

    range_text = (
        f"{start or '最早'}至{end or '最新'}" if (start or end) else "全部"
    )
    return buffer.getvalue(), f"预约报表_{range_text}.xlsx"
