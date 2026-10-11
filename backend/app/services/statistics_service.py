from datetime import datetime, time, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.equipment import Equipment
from app.models.lab import Lab
from app.models.reservation import Reservation
from app.models.user import User
from app.schemas.statistics import LabRankItem, StatisticsOverviewResponse, TrendPoint

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

    所有指标都从现有 4 张表现算，**不需要新表、新列**——这点很重要，项目没有迁移框架，
    建表只靠启动时的 Base.metadata.create_all（它只建缺失的表，给已有表加列不会生效）。
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
