"""一周占用网格的接口数据。

这块只给界面显示和点选，真正的冲突拦截仍然在 create_reservation 里，
所以这里验的是「数据范围对不对」：日期连续、周末不开放的写法、
整间实验室和设备看到的占用是否按 _busy_query 的规则分叉。
"""

from datetime import datetime, timedelta

import pytest

from app.common.exceptions import BusinessException
from app.services import reservation_service


MONDAY = 0
WEDNESDAY = 2
SATURDAY = 5
SUNDAY = 6


def _next_weekday(weekday: int) -> str:
    """往后（至少明天）找第一个星期几，格式 YYYY-MM-DD。"""
    day = datetime.now() + timedelta(days=1)
    for _ in range(7):
        if day.weekday() == weekday:
            return day.strftime("%Y-%m-%d")
        day += timedelta(days=1)
    raise AssertionError("一周之内一定找得到指定的星期几")


def test_week_schedule_gives_seven_days_and_marks_closed_weekend(db, make_lab):
    lab = make_lab(weekend_open_time="", weekend_close_time="")

    res = reservation_service.get_week_schedule(db, lab.id, _next_weekday(MONDAY))

    assert len(res.days) == 7
    # 从周一开始，第 6、第 7 天正好是周六和周日。
    assert res.days[0].weekday == MONDAY
    assert res.days[5].weekday == SATURDAY
    assert res.days[6].weekday == SUNDAY
    assert res.days[5].open_time is None
    assert res.days[5].close_time is None
    # 周中仍然按 open_time/close_time 给，不能被周末那条连带清空。
    assert res.days[0].open_time == "08:00"
    assert res.days[0].close_time == "21:00"


def test_week_schedule_busy_scope_differs_between_lab_and_equipment(
    db, make_user, make_lab, make_equipment, booking
):
    user = make_user()
    lab = make_lab()
    equipment_a = make_equipment(lab.id, name="设备A")
    equipment_b = make_equipment(lab.id, name="设备B")
    day = _next_weekday(WEDNESDAY)

    # A 的预约：只有 A 自己和整间实验室看得见。
    reservation_service.create_reservation(
        db,
        user,
        booking(
            lab.id,
            date=day,
            start_time="09:00",
            end_time="10:00",
            equipment_id=equipment_a.id,
        ),
    )
    # 整间实验室的预约：B 也应该看得见（同一间实验室共用一个场地）。
    reservation_service.create_reservation(
        db, user, booking(lab.id, date=day, start_time="11:00", end_time="12:00")
    )

    lab_view = reservation_service.get_week_schedule(db, lab.id, day)
    day_row = next(item for item in lab_view.days if item.date == day)
    assert [(b.start_time, b.end_time) for b in day_row.busy] == [
        ("09:00", "10:00"),
        ("11:00", "12:00"),
    ]

    equipment_view = reservation_service.get_week_schedule(
        db, lab.id, day, equipment_id=equipment_b.id
    )
    day_row = next(item for item in equipment_view.days if item.date == day)
    assert [(b.start_time, b.end_time) for b in day_row.busy] == [
        ("11:00", "12:00")
    ]


def test_week_schedule_api_requires_login_and_returns_days(
    client, make_user, make_lab, auth_headers
):
    user = make_user()
    lab = make_lab()

    unauthorized = client.get(
        "/api/reservation/week-schedule", params={"lab_id": lab.id}
    )
    assert unauthorized.status_code == 401

    body = client.get(
        "/api/reservation/week-schedule",
        params={"lab_id": lab.id},
        headers=auth_headers(user),
    ).json()
    assert body["code"] == 200
    assert len(body["data"]["days"]) == 7
    assert body["data"]["lab_name"] == lab.name


def test_week_schedule_rejects_bad_input(db, make_lab, make_equipment):
    lab = make_lab()
    disabled = make_lab(name="停用实验室", status=0)
    other = make_lab(name="别的实验室")
    foreign = make_equipment(other.id)

    with pytest.raises(BusinessException, match="日期格式"):
        reservation_service.get_week_schedule(db, lab.id, "2026-13-01")
    with pytest.raises(BusinessException, match="未开放预约"):
        reservation_service.get_week_schedule(db, disabled.id)
    with pytest.raises(BusinessException, match="不属于"):
        reservation_service.get_week_schedule(db, lab.id, equipment_id=foreign.id)
