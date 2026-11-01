"""预约变更时间线。

每变一次状态记一笔，且必须和预约状态本身同一个事务——只要有一条
「状态变了、时间线没记」或反过来，这条时间线就没法用来对账。

时钟统一钉死，用例不随跑在哪天、哪分钟变化。
"""

from datetime import datetime

import pytest

from app.common.exceptions import BusinessException
from app.models.reservation import Reservation
from app.models.reservation_log import ReservationLog
from app.services import reservation_service

DAY = "2026-10-14"  # 星期三
MORNING = datetime(2026, 10, 14, 6, 0)
NEXT_DAY_MORNING = datetime(2026, 10, 15, 6, 0)


def _freeze_clock(monkeypatch, moment):
    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment

    monkeypatch.setattr(reservation_service, "datetime", _FrozenDatetime)


def _create(db, user, request):
    reservation_service.create_reservation(db, user, request)
    return db.query(Reservation).order_by(Reservation.id.desc()).first()


def _logs(db, reservation_id):
    # 超时自动取消跑在自己的会话里；MySQL 默认 REPEATABLE READ，
    # 不结束当前事务就看不到它刚提交的行。
    db.rollback()
    return (
        db.query(ReservationLog)
        .filter(ReservationLog.reservation_id == reservation_id)
        .order_by(ReservationLog.id.asc())
        .all()
    )


class TestTimelineIsWritten:
    def test_create_writes_the_first_entry(
        self, db, make_user, make_lab, booking, monkeypatch
    ):
        _freeze_clock(monkeypatch, MORNING)
        user, lab = make_user(), make_lab()
        item = _create(
            db, user, booking(lab.id, date=DAY, start_time="09:00", end_time="10:00")
        )

        logs = _logs(db, item.id)
        assert len(logs) == 1
        assert logs[0].action == "create"
        assert logs[0].from_status is None
        assert logs[0].to_status == 0
        assert logs[0].operator_id == user.id
        assert logs[0].operator_name == user.name

    def test_approve_and_reject_are_attributed(
        self, db, make_user, make_lab, booking, monkeypatch
    ):
        _freeze_clock(monkeypatch, MORNING)
        admin = make_user(username="boss", role="admin")
        user, lab = make_user(username="stu"), make_lab()

        approved = _create(
            db, user, booking(lab.id, date=DAY, start_time="09:00", end_time="10:00")
        )
        reservation_service.audit_reservation(
            db, approved.id, 1, operator=admin
        )
        rejected = _create(
            db, user, booking(lab.id, date=DAY, start_time="10:00", end_time="11:00")
        )
        reservation_service.audit_reservation(db, rejected.id, 2, operator=admin)

        approve_log = _logs(db, approved.id)[-1]
        assert approve_log.action == "approve"
        assert (approve_log.from_status, approve_log.to_status) == (0, 1)
        assert approve_log.operator_id == admin.id
        assert approve_log.operator_name == admin.name

        reject_log = _logs(db, rejected.id)[-1]
        assert reject_log.action == "reject"
        assert (reject_log.from_status, reject_log.to_status) == (0, 2)

    def test_owner_cancel_keeps_the_previous_status(
        self, db, make_user, make_lab, booking, monkeypatch
    ):
        _freeze_clock(monkeypatch, MORNING)
        admin = make_user(username="boss", role="admin")
        user, lab = make_user(), make_lab()

        item = _create(
            db, user, booking(lab.id, date=DAY, start_time="09:00", end_time="10:00")
        )
        reservation_service.audit_reservation(db, item.id, 1, operator=admin)
        reservation_service.cancel_reservation(db, user, item.id)

        logs = _logs(db, item.id)
        assert [log.action for log in logs] == ["create", "approve", "cancel"]
        # 已通过的取消，前状态必须是"已通过"而不是从 0 直接跳 3
        assert (logs[-1].from_status, logs[-1].to_status) == (1, 3)
        assert logs[-1].operator_id == user.id

    def test_force_cancel_records_reason_and_operator(
        self, db, make_user, make_lab, booking, monkeypatch
    ):
        _freeze_clock(monkeypatch, MORNING)
        admin = make_user(username="boss", role="admin")
        user, lab = make_user(), make_lab()
        item = _create(
            db, user, booking(lab.id, date=DAY, start_time="09:00", end_time="10:00")
        )

        reservation_service.force_cancel_reservation(
            db, item.id, "设备临时故障", operator=admin
        )

        log = _logs(db, item.id)[-1]
        assert log.action == "force_cancel"
        assert log.reason == "设备临时故障"
        assert log.operator_id == admin.id
        assert log.operator_name == admin.name

    def test_force_cancel_without_operator_says_admin(
        self, db, make_user, make_lab, booking, monkeypatch
    ):
        """老的调用方不传操作人；时间线上留空会像"系统干的"，要说成管理员。"""
        _freeze_clock(monkeypatch, MORNING)
        user, lab = make_user(), make_lab()
        item = _create(
            db, user, booking(lab.id, date=DAY, start_time="09:00", end_time="10:00")
        )

        reservation_service.force_cancel_reservation(db, item.id, "实验室检修")

        log = _logs(db, item.id)[-1]
        assert log.operator_id is None
        assert log.operator_name == "管理员"
        assert log.reason == "实验室检修"

    def test_auto_cancel_is_attributed_to_the_system(
        self, db, make_user, make_lab, booking, monkeypatch
    ):
        _freeze_clock(monkeypatch, MORNING)
        user, lab = make_user(), make_lab()
        item = _create(
            db, user, booking(lab.id, date=DAY, start_time="09:00", end_time="10:00")
        )

        # 第二天再跑扫描：前一天的待审核预约超时了
        _freeze_clock(monkeypatch, NEXT_DAY_MORNING)
        reservation_service.expire_pending_reservations()

        log = _logs(db, item.id)[-1]
        assert log.action == "auto_cancel"
        assert (log.from_status, log.to_status) == (0, 3)
        assert log.operator_id is None
        assert log.operator_name == "系统"
        assert log.reason == reservation_service.AUTO_CANCEL_REASON


class TestTimelineApi:
    def _setup(self, db, make_user, make_lab, booking, monkeypatch):
        _freeze_clock(monkeypatch, MORNING)
        admin = make_user(username="boss", role="admin")
        owner = make_user(username="owner")
        other = make_user(username="other")
        lab = make_lab()
        item = _create(
            db, owner, booking(lab.id, date=DAY, start_time="09:00", end_time="10:00")
        )
        reservation_service.audit_reservation(db, item.id, 1, operator=admin)
        return admin, owner, other, item

    def test_owner_can_read_timeline(
        self, client, db, make_user, make_lab, booking, auth_headers, monkeypatch
    ):
        _admin, owner, _other, item = self._setup(
            db, make_user, make_lab, booking, monkeypatch
        )

        body = client.get(
            f"/api/reservation/{item.id}/logs", headers=auth_headers(owner)
        ).json()
        assert body["code"] == 200
        assert [entry["action"] for entry in body["data"]] == ["create", "approve"]

    def test_admin_can_read_any_timeline(
        self, client, db, make_user, make_lab, booking, auth_headers, monkeypatch
    ):
        admin, _owner, _other, item = self._setup(
            db, make_user, make_lab, booking, monkeypatch
        )

        body = client.get(
            f"/api/reservation/{item.id}/logs", headers=auth_headers(admin)
        ).json()
        assert body["code"] == 200
        assert body["data"][0]["operator_name"]

    def test_other_student_is_rejected(
        self, client, db, make_user, make_lab, booking, auth_headers, monkeypatch
    ):
        _admin, _owner, other, item = self._setup(
            db, make_user, make_lab, booking, monkeypatch
        )

        body = client.get(
            f"/api/reservation/{item.id}/logs", headers=auth_headers(other)
        ).json()
        assert body["code"] == 403

    def test_missing_reservation_is_rejected(
        self, client, db, make_user, auth_headers
    ):
        user = make_user(username="stu")

        body = client.get(
            "/api/reservation/999999/logs", headers=auth_headers(user)
        ).json()
        assert body["code"] == 400
        assert body["message"] == "预约记录不存在"
