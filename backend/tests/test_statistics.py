"""统计概览接口（GET /api/statistics/overview）的用例。

重点不是"接口返回 200"，而是**统计口径本身**：哪些数据算进来、按哪个时间分组、状态怎么
分桶、排行怎么排序、谁看得见谁的数据。所以每个用例都先造出"已知构成"的数据，再断言精确的
数值 / 长度 / 顺序。

五个维度各有用例覆盖：角色 scoping、状态分桶、create_time vs date、补零与窗口边界、
排行顺序与上限。
"""

from datetime import datetime, time, timedelta

from app.models.reservation import Reservation
from app.services import statistics_service

OVERVIEW = "/api/statistics/overview"


def _add_reservation(
    db,
    lab_id,
    user_id,
    status=0,
    create_time=None,
    equipment_id=None,
    date=None,
    start_time="09:00",
    end_time="10:00",
):
    """直接往库里插一行预约。

    不走 create_reservation 是故意的：那个服务只产出 status=0，审核也只能 0→1/2，
    造不出 3（已取消），更没法指定 create_time。create_time 是 Python 侧的 default，
    显式传参就能覆盖它。
    """
    if date is None:
        date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    extra = {}
    if create_time is not None:
        extra["create_time"] = create_time
    row = Reservation(
        user_id=user_id,
        lab_id=lab_id,
        equipment_id=equipment_id,
        date=date,
        start_time=start_time,
        end_time=end_time,
        status=status,
        **extra,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _overview(client, user, auth_headers):
    """打一次接口，顺带钉住信封形状，返回 data"""
    resp = client.get(OVERVIEW, headers=auth_headers(user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    return body["data"]


def _trend_map(data):
    return {point["date"]: point["count"] for point in data["reservation_trend"]}


# ---------------------------------------------------------------- 鉴权与空库


def test_overview_requires_login(client):
    """匿名访问被 get_current_user 拦下。注意这条走的是真 HTTP 401
    （依赖里抛的是 HTTPException），不是业务异常那种 HTTP 200 + body.code。"""
    assert client.get(OVERVIEW).status_code == 401


def test_empty_db_shape(client, make_user, auth_headers):
    """空库不能抛异常：全 0、趋势仍是 7 个 0、排行为空"""
    admin = make_user(username="admin1", role="admin")

    data = _overview(client, admin, auth_headers)
    assert data["lab_total"] == 0
    assert data["lab_open_total"] == 0
    assert data["equipment_total"] == 0
    assert data["reservation_total"] == 0
    assert data["reservation_trend"] and len(data["reservation_trend"]) == 7
    assert all(point["count"] == 0 for point in data["reservation_trend"])
    assert data["lab_ranking"] == []


# ---------------------------------------------------------------- 实验室 / 设备计数


def test_lab_and_equipment_counts(client, make_user, make_lab, make_equipment, auth_headers):
    """状态要真的区分开：数量造得不相等，写错过滤条件就会露馅"""
    stu = make_user(username="stu1")
    lab_open = make_lab(name="开放的", status=1)
    make_lab(name="关闭的", status=0)
    make_equipment(lab_open.id, name="正常1", status=1)
    make_equipment(lab_open.id, name="正常2", status=1)
    make_equipment(lab_open.id, name="维修中", status=0)

    data = _overview(client, stu, auth_headers)
    assert data["lab_total"] == 2
    assert data["lab_open_total"] == 1
    assert data["equipment_total"] == 3
    assert data["equipment_normal_total"] == 2
    assert data["equipment_repair_total"] == 1


# ---------------------------------------------------------------- 角色 scoping


def test_reservation_status_counts_admin(client, db, make_user, make_lab, auth_headers):
    """管理员看全库，且四个状态各归各的桶"""
    admin = make_user(username="admin1", role="admin")
    stu = make_user(username="stu1")
    lab = make_lab()
    for status, times in [(0, 2), (1, 3), (2, 1), (3, 4)]:
        for _ in range(times):
            _add_reservation(db, lab.id, stu.id, status=status)

    data = _overview(client, admin, auth_headers)
    assert data["reservation_pending_total"] == 2
    assert data["reservation_approved_total"] == 3
    assert data["reservation_rejected_total"] == 1
    assert data["reservation_canceled_total"] == 4
    # 总数必须等于各状态之和，不能是一个单独 count 出来的数
    assert data["reservation_total"] == 10
    assert data["reservation_total"] == (
        data["reservation_pending_total"]
        + data["reservation_approved_total"]
        + data["reservation_rejected_total"]
        + data["reservation_canceled_total"]
    )


def test_student_sees_only_own_reservations(
    client, db, make_user, make_lab, make_equipment, auth_headers
):
    """学生只看得到自己的预约；但实验室/设备是全局资源，仍返回全库值"""
    lab = make_lab()
    make_equipment(lab.id)
    stu_a = make_user(username="stu_a")
    stu_b = make_user(username="stu_b")
    _add_reservation(db, lab.id, stu_a.id, status=0)
    _add_reservation(db, lab.id, stu_a.id, status=1)
    _add_reservation(db, lab.id, stu_b.id, status=1)

    data = _overview(client, stu_a, auth_headers)
    assert data["reservation_total"] == 2
    assert data["reservation_pending_total"] == 1
    assert data["reservation_approved_total"] == 1
    # 这两个不按角色过滤：写反了（把 lab/equipment 也 scope 到 user）这里就会是 0
    assert data["lab_total"] == 1
    assert data["equipment_total"] == 1


# ---------------------------------------------------------------- 趋势


def test_trend_zero_filled_seven_days(client, db, make_user, make_lab, auth_headers):
    """长度恒为 7、日期连续升序含今天、没有预约的天补 0"""
    admin = make_user(username="admin1", role="admin")
    lab = make_lab()
    # 取当天正午当基准，避免用"现在"时踩到跨日的边界
    base = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    for _ in range(2):
        _add_reservation(db, lab.id, admin.id, create_time=base)
    _add_reservation(db, lab.id, admin.id, create_time=base - timedelta(days=3))
    for _ in range(3):
        _add_reservation(db, lab.id, admin.id, create_time=base - timedelta(days=6))

    data = _overview(client, admin, auth_headers)
    trend = data["reservation_trend"]
    assert len(trend) == 7

    today = datetime.now().date()
    expected_days = [(today - timedelta(days=6 - i)).strftime("%Y-%m-%d") for i in range(7)]
    assert [point["date"] for point in trend] == expected_days

    counted = _trend_map(data)
    assert counted[expected_days[6]] == 2  # 今天
    assert counted[expected_days[3]] == 1  # 3 天前
    assert counted[expected_days[0]] == 3  # 6 天前
    assert counted[expected_days[2]] == 0  # 没预约的那天补 0


def test_trend_uses_create_time_not_reserve_date(client, db, make_user, make_lab, auth_headers):
    """口径判别式：趋势按"下单时间"分组，不是按"预约哪天来用"。

    两条数据互为反例，把口径钉死：
    - 目标日期在明天（窗口外），但下单时间在今天（窗口内）→ 必须计入今天
    - 目标日期在今天（看着在窗口内），但下单时间在 10 天前（窗口外）→ 一条都不该进
    用 date 分组的话这两条的归属会正好反过来。
    """
    admin = make_user(username="admin1", role="admin")
    lab = make_lab()
    now = datetime.now()
    today = now.date().strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    _add_reservation(db, lab.id, admin.id, date=tomorrow, create_time=now)
    _add_reservation(db, lab.id, admin.id, date=today, create_time=now - timedelta(days=10))

    data = _overview(client, admin, auth_headers)
    counted = _trend_map(data)
    assert counted[today] == 1
    assert sum(counted.values()) == 1


def test_trend_window_boundary(client, db, make_user, make_lab, auth_headers):
    """左边界：窗口第一天 00:00 计入，再早一天不计入"""
    admin = make_user(username="admin1", role="admin")
    lab = make_lab()
    start_day = datetime.now().date() - timedelta(days=6)

    _add_reservation(db, lab.id, admin.id, create_time=datetime.combine(start_day, time.min))
    _add_reservation(
        db,
        lab.id,
        admin.id,
        create_time=datetime.combine(start_day - timedelta(days=1), time.min),
    )

    data = _overview(client, admin, auth_headers)
    counted = _trend_map(data)
    assert sum(counted.values()) == 1
    assert counted[start_day.strftime("%Y-%m-%d")] == 1


# ---------------------------------------------------------------- 实验室排行


def test_lab_ranking_order_and_limit(client, db, make_user, make_lab, auth_headers):
    """降序、最多 5 项；6 个实验室时同分的那批按 lab_id 升序取名次"""
    admin = make_user(username="admin1", role="admin")
    labs = [make_lab(name=f"实验室{i}") for i in range(6)]
    for _ in range(5):
        _add_reservation(db, labs[2].id, admin.id)
    for lab in (labs[0], labs[1], labs[3], labs[4], labs[5]):
        _add_reservation(db, lab.id, admin.id)

    ranking = _overview(client, admin, auth_headers)["lab_ranking"]
    assert len(ranking) == 5
    assert ranking[0]["lab_id"] == labs[2].id
    assert ranking[0]["count"] == 5
    assert ranking[0]["lab_name"] == "实验室2"

    counts = [item["count"] for item in ranking]
    assert counts == sorted(counts, reverse=True)
    # 5 个同分的里面，lab_id 最大的那个被挤出去
    ranked_ids = [item["lab_id"] for item in ranking]
    assert labs[5].id not in ranked_ids


def test_lab_ranking_excludes_canceled_and_rejected(
    client, db, make_user, make_lab, auth_headers
):
    """口径 = status in (0, 1)，跟 _busy_query 一致：已拒绝(2)/已取消(3) 不进榜"""
    admin = make_user(username="admin1", role="admin")
    lab_valid = make_lab(name="有效的")
    lab_dead = make_lab(name="全被拒的")
    _add_reservation(db, lab_valid.id, admin.id, status=1)
    _add_reservation(db, lab_dead.id, admin.id, status=2)
    _add_reservation(db, lab_dead.id, admin.id, status=3)

    ranking = _overview(client, admin, auth_headers)["lab_ranking"]
    assert [item["lab_id"] for item in ranking] == [lab_valid.id]
    assert ranking[0]["count"] == 1


def test_student_ranking_scoped_to_self(client, db, make_user, make_lab, auth_headers):
    """排行也分角色：学生看到的是"我自己约得最多的实验室"，不是全库排行"""
    lab_a = make_lab(name="A")
    lab_b = make_lab(name="B")
    stu = make_user(username="stu1")
    other = make_user(username="stu2")
    _add_reservation(db, lab_a.id, stu.id)
    _add_reservation(db, lab_a.id, stu.id)
    for _ in range(3):
        _add_reservation(db, lab_b.id, other.id)

    data = _overview(client, stu, auth_headers)
    assert [item["lab_id"] for item in data["lab_ranking"]] == [lab_a.id]
    assert data["lab_ranking"][0]["count"] == 2


def test_ranking_tie_break_is_stable(client, db, make_user, make_lab, auth_headers):
    """平手按 lab_id 升序：顺序由 id 决定，不由插入顺序或数据库心情决定"""
    admin = make_user(username="admin1", role="admin")
    first = make_lab(name="甲")
    second = make_lab(name="乙")
    # 故意先插 second（id 更大），证明结果顺序不是"谁先插谁在前"
    for lab in (second, first):
        _add_reservation(db, lab.id, admin.id)
        _add_reservation(db, lab.id, admin.id)

    first_call = _overview(client, admin, auth_headers)["lab_ranking"]
    second_call = _overview(client, admin, auth_headers)["lab_ranking"]
    assert [item["lab_id"] for item in first_call] == [first.id, second.id]
    assert [item["lab_id"] for item in first_call] == [
        item["lab_id"] for item in second_call
    ]


# ---------------------------------------------------------------- service 层直调


def test_service_returns_response_model(db, make_user, make_lab):
    """service 直调也能拿到完整的响应模型（接口层只是套了个信封）"""
    admin = make_user(username="admin1", role="admin")
    lab = make_lab()
    _add_reservation(db, lab.id, admin.id)

    result = statistics_service.get_overview(db, admin)
    assert result.reservation_total == 1
    assert len(result.reservation_trend) == 7
    assert result.lab_ranking[0].lab_id == lab.id
