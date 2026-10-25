"""取消规则：待审核随时可取消；已通过只在开始前 N 小时以上能取消；
管理员可以越过截止线强制取消，但必须写原因。

N 取 settings.RESERVATION_CANCEL_DEADLINE_HOURS（默认 2 小时）。
时钟统一用 `_freeze_clock` 钉死，用例不随跑在哪一天、哪一分钟变化。
"""

from datetime import datetime

import pytest

from app.common.exceptions import BusinessException
from app.models.reservation import Reservation
from app.services import reservation_service

DAY = "2026-10-14"  # 星期三
MORNING = datetime(2026, 10, 14, 6, 0)


def _freeze_clock(monkeypatch, moment):
    """把 reservation_service 里的 datetime.now() 钉在某一刻。"""

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment

    monkeypatch.setattr(reservation_service, "datetime", _FrozenDatetime)


def _create(db, user, request):
    reservation_service.create_reservation(db, user, request)
    return db.query(Reservation).order_by(Reservation.id.desc()).first()


def _create_approved(db, user, request):
    item = _create(db, user, request)
    reservation_service.audit_reservation(db, item.id, 1)
    db.refresh(item)
    return item


class TestOwnerCancel:
    def test_pending_can_cancel_anytime(
        self, db, make_user, make_lab, booking, monkeypatch
    ):
        """待审核的预约即使离开始只剩半小时，也能取消。"""
        _freeze_clock(monkeypatch, datetime(2026, 10, 14, 8, 30))
        user, lab = make_user(), make_lab()
        item = _create(
            db,
            user,
            booking(lab.id, date=DAY, start_time="09:00", end_time="10:00"),
        )

        reservation_service.cancel_reservation(db, user, item.id)
        db.refresh(item)
        assert item.status == 3
        assert item.cancel_time is not None
        assert item.cancel_reason is None

    def test_approved_more_than_deadline_can_cancel(
        self, db, make_user, make_lab, booking, monkeypatch
    ):
        _freeze_clock(monkeypatch, MORNING)  # 06:00，距 09:00 还有 3 小时
        user, lab = make_user(), make_lab()
        item = _create_approved(
            db,
            user,
            booking(lab.id, date=DAY, start_time="09:00", end_time="10:00"),
        )

        reservation_service.cancel_reservation(db, user, item.id)
        db.refresh(item)
        assert item.status == 3
        assert item.cancel_time == MORNING

    def test_exactly_at_deadline_is_allowed(
        self, db, make_user, make_lab, booking, monkeypatch
    ):
        """截止线是"不足 2 小时才锁"，正好 2 小时应当放行。"""
        _freeze_clock(monkeypatch, datetime(2026, 10, 14, 7, 0))
        user, lab = make_user(), make_lab()
        item = _create_approved(
            db,
            user,
            booking(lab.id, date=DAY, start_time="09:00", end_time="10:00"),
        )

        reservation_service.cancel_reservation(db, user, item.id)
        db.refresh(item)
        assert item.status == 3

    def test_approved_within_deadline_is_locked(
        self, db, make_user, make_lab, booking, monkeypatch
    ):
        _freeze_clock(monkeypatch, datetime(2026, 10, 14, 8, 0))  # 只剩 1 小时
        user, lab = make_user(), make_lab()
        item = _create_approved(
            db,
            user,
            booking(lab.id, date=DAY, start_time="09:00", end_time="10:00"),
        )

        with pytest.raises(BusinessException) as exc:
            reservation_service.cancel_reservation(db, user, item.id)
        assert "小时内不能自行取消" in exc.value.message

        db.refresh(item)
        assert item.status == 1

    def test_rejected_cannot_cancel(
        self, db, make_user, make_lab, booking, monkeypatch
    ):
        _freeze_clock(monkeypatch, MORNING)
        user, lab = make_user(), make_lab()
        item = _create(
            db,
            user,
            booking(lab.id, date=DAY, start_time="09:00", end_time="10:00"),
        )
        reservation_service.audit_reservation(db, item.id, 2)

        with pytest.raises(BusinessException) as exc:
            reservation_service.cancel_reservation(db, user, item.id)
        assert exc.value.message == "当前状态的预约不能取消"

    def test_already_canceled_cannot_cancel_again(
        self, db, make_user, make_lab, booking, monkeypatch
    ):
        _freeze_clock(monkeypatch, MORNING)
        user, lab = make_user(), make_lab()
        item = _create(
            db,
            user,
            booking(lab.id, date=DAY, start_time="09:00", end_time="10:00"),
        )
        reservation_service.cancel_reservation(db, user, item.id)

        with pytest.raises(BusinessException) as exc:
            reservation_service.cancel_reservation(db, user, item.id)
        assert exc.value.message == "当前状态的预约不能取消"

    def test_other_user_cannot_cancel(
        self, db, make_user, make_lab, booking, monkeypatch
    ):
        _freeze_clock(monkeypatch, MORNING)
        owner, other = make_user(username="owner"), make_user(username="other")
        lab = make_lab()
        item = _create(
            db,
            owner,
            booking(lab.id, date=DAY, start_time="09:00", end_time="10:00"),
        )

        with pytest.raises(BusinessException) as exc:
            reservation_service.cancel_reservation(db, other, item.id)
        assert exc.value.code == 403

    def test_cancel_frees_the_slot(
        self, db, make_user, make_lab, booking, monkeypatch
    ):
        _freeze_clock(monkeypatch, MORNING)
        first, second = make_user(username="first"), make_user(username="second")
        lab = make_lab()
        item = _create(
            db,
            first,
            booking(lab.id, date=DAY, start_time="09:00", end_time="10:00"),
        )
        reservation_service.cancel_reservation(db, first, item.id)

        # 同一时段现在应当能再约出去
        _create(
            db,
            second,
            booking(lab.id, date=DAY, start_time="09:00", end_time="10:00"),
        )
        assert db.query(Reservation).count() == 2


class TestForceCancel:
    def test_approved_can_be_force_canceled_with_reason(
        self, db, make_user, make_lab, booking, monkeypatch
    ):
        _freeze_clock(monkeypatch, MORNING)
        user, lab = make_user(), make_lab()
        item = _create_approved(
            db,
            user,
            booking(lab.id, date=DAY, start_time="09:00", end_time="10:00"),
        )

        reservation_service.force_cancel_reservation(db, item.id, "设备临时故障")
        db.refresh(item)
        assert item.status == 3
        assert item.cancel_reason == "设备临时故障"
        assert item.cancel_time == MORNING

    def test_pending_can_be_force_canceled(
        self, db, make_user, make_lab, booking, monkeypatch
    ):
        _freeze_clock(monkeypatch, MORNING)
        user, lab = make_user(), make_lab()
        item = _create(
            db,
            user,
            booking(lab.id, date=DAY, start_time="09:00", end_time="10:00"),
        )

        reservation_service.force_cancel_reservation(db, item.id, "实验室检修")
        db.refresh(item)
        assert item.status == 3
        assert item.cancel_reason == "实验室检修"

    def test_finished_status_cannot_be_force_canceled(
        self, db, make_user, make_lab, booking, monkeypatch
    ):
        _freeze_clock(monkeypatch, MORNING)
        user, lab = make_user(), make_lab()
        item = _create(
            db,
            user,
            booking(lab.id, date=DAY, start_time="09:00", end_time="10:00"),
        )
        reservation_service.audit_reservation(db, item.id, 2)

        with pytest.raises(BusinessException) as exc:
            reservation_service.force_cancel_reservation(db, item.id, "临时调整")
        assert exc.value.message == "当前状态的预约不能取消"


class TestForceCancelApi:
    def _setup(self, db, make_user, make_lab, booking, monkeypatch):
        _freeze_clock(monkeypatch, MORNING)
        admin = make_user(username="root", role="admin")
        user = make_user(username="stu")
        lab = make_lab()
        item = _create_approved(
            db,
            user,
            booking(lab.id, date=DAY, start_time="09:00", end_time="10:00"),
        )
        return admin, user, item

    def test_admin_can_force_cancel(
        self, client, db, make_user, make_lab, booking, auth_headers, monkeypatch
    ):
        admin, _user, item = self._setup(
            db, make_user, make_lab, booking, monkeypatch
        )

        body = client.put(
            f"/api/reservation/{item.id}/force-cancel",
            headers=auth_headers(admin),
            json={"reason": "设备故障"},
        ).json()
        assert body["code"] == 200, body

        db.rollback()
        fresh = db.query(Reservation).filter(Reservation.id == item.id).one()
        assert fresh.status == 3
        assert fresh.cancel_reason == "设备故障"

    def test_non_admin_is_rejected(
        self, client, db, make_user, make_lab, booking, auth_headers, monkeypatch
    ):
        _admin, user, item = self._setup(
            db, make_user, make_lab, booking, monkeypatch
        )

        body = client.put(
            f"/api/reservation/{item.id}/force-cancel",
            headers=auth_headers(user),
            json={"reason": "我想取消"},
        ).json()
        assert body["code"] == 403

    def test_reason_is_required(
        self, client, db, make_user, make_lab, booking, auth_headers, monkeypatch
    ):
        admin, _user, item = self._setup(
            db, make_user, make_lab, booking, monkeypatch
        )

        # 空白、只有一个字都不行：用户看到的"取消原因"不能是空的
        for reason in ("", " ", "坏"):
            resp = client.put(
                f"/api/reservation/{item.id}/force-cancel",
                headers=auth_headers(admin),
                json={"reason": reason},
            )
            assert resp.status_code == 422


class TestCanCancelFlagInList:
    def test_flags_match_the_rules(
        self, db, make_user, make_lab, booking, monkeypatch
    ):
        """前端按钮亮不亮完全看这个字段，必须跟取消接口的判断一致。"""
        _freeze_clock(monkeypatch, datetime(2026, 10, 14, 7, 0))
        user, lab = make_user(), make_lab()

        pending = _create(
            db,
            user,
            booking(lab.id, date=DAY, start_time="08:00", end_time="08:30"),
        )
        # 08:30 离 07:00 只有 1.5 小时 → 已通过也不能取消
        near = _create_approved(
            db,
            user,
            booking(lab.id, date=DAY, start_time="08:30", end_time="09:00"),
        )
        # 09:30 离 07:00 有 2.5 小时 → 可以取消
        far = _create_approved(
            db,
            user,
            booking(lab.id, date=DAY, start_time="09:30", end_time="10:00"),
        )

        page = reservation_service.get_reservation_page_list(db, user, 1, 10)
        flags = {item.id: item.can_cancel for item in page.list}
        assert flags[pending.id] is True
        assert flags[near.id] is False
        assert flags[far.id] is True

    def test_date_filters(
        self, db, make_user, make_lab, booking, monkeypatch
    ):
        _freeze_clock(monkeypatch, MORNING)
        user, lab = make_user(), make_lab()
        for date in ("2026-10-14", "2026-10-16", "2026-10-18"):
            _create(
                db,
                user,
                booking(lab.id, date=date, start_time="09:00", end_time="10:00"),
            )

        page = reservation_service.get_reservation_page_list(
            db, user, 1, 10, date_from="2026-10-15", date_to="2026-10-17"
        )
        assert page.total == 1
        assert page.list[0].date == "2026-10-16"

    def test_date_from_after_date_to_rejected(
        self, db, make_user, monkeypatch
    ):
        _freeze_clock(monkeypatch, MORNING)
        user = make_user()

        with pytest.raises(BusinessException) as exc:
            reservation_service.get_reservation_page_list(
                db, user, 1, 10, date_from="2026-10-18", date_to="2026-10-15"
            )
        assert exc.value.message == "开始日期不能晚于结束日期"
