"""管理端首页待办工作台（GET /api/statistics/admin-workbench）。

口径要点：
- 只给管理员，学生拿到 403（HTTP 200 + body.code，跟项目其余业务错误一致）。
- “今日预约”只算待审核和已通过，已拒绝/已取消不算——那些名额今天不会有人来。
- “近 7 天自动取消”只认系统写的那句原因，管理员手动取消不算。
"""

from datetime import datetime, timedelta

from app.models.reservation import Reservation
from app.services import reservation_service

WORKBENCH = "/api/statistics/admin-workbench"


def _add(
    db,
    lab_id,
    user_id,
    *,
    status=0,
    date=None,
    equipment_id=None,
    cancel_reason=None,
    cancel_time=None,
    create_time=None,
):
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
        start_time="09:00",
        end_time="10:00",
        status=status,
        cancel_reason=cancel_reason,
        cancel_time=cancel_time,
        **extra,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _data(client, user, auth_headers):
    body = client.get(WORKBENCH, headers=auth_headers(user)).json()
    assert body["code"] == 200, body
    return body["data"]


def test_requires_login(client):
    assert client.get(WORKBENCH).status_code == 401


def test_only_admin(client, make_user, auth_headers):
    student = make_user(username="stu")
    body = client.get(WORKBENCH, headers=auth_headers(student)).json()
    assert body["code"] == 403


def test_empty_db(client, make_user, auth_headers):
    admin = make_user(username="admin", role="admin")
    data = _data(client, admin, auth_headers)
    assert data["pending_total"] == 0
    assert data["today_total"] == 0
    assert data["today_pending_total"] == 0
    assert data["auto_canceled_7d"] == 0
    assert data["pending_list"] == []


def test_counts_use_the_right_scope(
    client, db, make_user, make_lab, auth_headers
):
    admin = make_user(username="admin", role="admin")
    stu = make_user(username="stu")
    lab = make_lab()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # 待审核：今天 1 条、明天 1 条
    _add(db, lab.id, stu.id, status=0, date=today)
    _add(db, lab.id, stu.id, status=0, date=tomorrow)
    # 已通过今天 1 条；已拒绝和已取消的今天各 1 条，都不该进“今日预约”
    _add(db, lab.id, stu.id, status=1, date=today)
    _add(db, lab.id, stu.id, status=2, date=today)
    _add(db, lab.id, stu.id, status=3, date=today)
    # 自动取消：7 天内 1 条、8 天前 1 条（后者不算）
    _add(
        db,
        lab.id,
        stu.id,
        status=3,
        cancel_reason=reservation_service.AUTO_CANCEL_REASON,
        cancel_time=now - timedelta(days=1),
    )
    _add(
        db,
        lab.id,
        stu.id,
        status=3,
        cancel_reason=reservation_service.AUTO_CANCEL_REASON,
        cancel_time=now - timedelta(days=8),
    )
    # 管理员手动取消，原因不同，不该混进“自动取消”
    _add(db, lab.id, stu.id, status=3, cancel_reason="设备故障")

    data = _data(client, admin, auth_headers)
    assert data["pending_total"] == 2
    assert data["today_total"] == 2
    assert data["today_pending_total"] == 1
    assert data["auto_canceled_7d"] == 1


def test_pending_list_is_oldest_first_and_capped(
    client, db, make_user, make_lab, make_equipment, auth_headers
):
    admin = make_user(username="admin", role="admin")
    stu = make_user(username="张三")
    lab = make_lab(name="计算机实验室")
    equipment = make_equipment(lab.id, name="RTX4090")
    base = datetime.now() - timedelta(hours=10)

    rows = []
    for index in range(6):
        rows.append(
            _add(
                db,
                lab.id,
                stu.id,
                status=0,
                equipment_id=equipment.id if index == 0 else None,
                create_time=base + timedelta(minutes=index),
            )
        )

    data = _data(client, admin, auth_headers)
    pending = data["pending_list"]
    assert len(pending) == 5
    # 最早提交的排第一，最晚的那条被挤出去
    assert [item["id"] for item in pending] == [row.id for row in rows[:5]]
    assert pending[0]["user_name"] == "张三"
    assert pending[0]["lab_name"] == "计算机实验室"
    assert pending[0]["equipment_name"] == "RTX4090"
    assert pending[0]["create_time"] is not None
