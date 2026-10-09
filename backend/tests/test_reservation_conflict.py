"""预约冲突的边界值与校验规则。

create_reservation 的重叠判定是：
    start_time < 新end AND end_time > 新start
这是一个半开区间 [start, end) 的判定——首尾相接（10:00 结束接 10:00 开始）
不算冲突。这个文件把这条边界和周边规则全部钉死。
"""

from datetime import datetime, timedelta

import pytest

from app.common.exceptions import BusinessException
from app.models.reservation import Reservation
from app.services import reservation_service


def _book(db, user, request):
    return reservation_service.create_reservation(db, user, request)


def _count(db):
    return db.query(Reservation).count()


class TestOverlapBoundary:
    """已有 09:00-10:00 时，哪些时段还能约、哪些不能"""

    def test_adjacent_before_is_ok(self, db, make_user, make_lab, booking):
        """08:00-09:00 顶着 09:00 结束 —— 首尾相接，不算冲突"""
        user, lab = make_user(), make_lab()
        _book(db, user, booking(lab.id, start_time="09:00", end_time="10:00"))
        _book(db, user, booking(lab.id, start_time="08:00", end_time="09:00"))
        assert _count(db) == 2

    def test_adjacent_after_is_ok(self, db, make_user, make_lab, booking):
        """10:00-11:00 接着 10:00 开始 —— 同样不算冲突"""
        user, lab = make_user(), make_lab()
        _book(db, user, booking(lab.id, start_time="09:00", end_time="10:00"))
        _book(db, user, booking(lab.id, start_time="10:00", end_time="11:00"))
        assert _count(db) == 2

    def test_overlap_at_head_is_rejected(self, db, make_user, make_lab, booking):
        """08:30-09:30 咬住了已有预约的头"""
        user, lab = make_user(), make_lab()
        _book(db, user, booking(lab.id, start_time="09:00", end_time="10:00"))
        with pytest.raises(BusinessException, match="实验室已被预约"):
            _book(db, user, booking(lab.id, start_time="08:30", end_time="09:30"))
        assert _count(db) == 1

    def test_overlap_at_tail_is_rejected(self, db, make_user, make_lab, booking):
        """09:30-10:30 咬住了已有预约的尾"""
        user, lab = make_user(), make_lab()
        _book(db, user, booking(lab.id, start_time="09:00", end_time="10:00"))
        with pytest.raises(BusinessException, match="实验室已被预约"):
            _book(db, user, booking(lab.id, start_time="09:30", end_time="10:30"))
        assert _count(db) == 1

    def test_fully_contained_is_rejected(self, db, make_user, make_lab, booking):
        """09:15-09:45 完全落在已有预约内部"""
        user, lab = make_user(), make_lab()
        _book(db, user, booking(lab.id, start_time="09:00", end_time="10:00"))
        with pytest.raises(BusinessException, match="实验室已被预约"):
            _book(db, user, booking(lab.id, start_time="09:15", end_time="09:45"))
        assert _count(db) == 1

    def test_fully_containing_is_rejected(self, db, make_user, make_lab, booking):
        """08:00-11:00 把已有预约整个包住"""
        user, lab = make_user(), make_lab()
        _book(db, user, booking(lab.id, start_time="09:00", end_time="10:00"))
        with pytest.raises(BusinessException, match="实验室已被预约"):
            _book(db, user, booking(lab.id, start_time="08:00", end_time="11:00"))
        assert _count(db) == 1

    def test_exact_same_slot_is_rejected(self, db, make_user, make_lab, booking):
        """一模一样的时间段"""
        user, lab = make_user(), make_lab()
        _book(db, user, booking(lab.id, start_time="09:00", end_time="10:00"))
        with pytest.raises(BusinessException, match="实验室已被预约"):
            _book(db, user, booking(lab.id, start_time="09:00", end_time="10:00"))
        assert _count(db) == 1

    def test_different_day_is_ok(self, db, make_user, make_lab, booking):
        """同一天同一时段，换一天就该能约"""
        user, lab = make_user(), make_lab()
        d1 = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        d2 = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        _book(db, user, booking(lab.id, date=d1, start_time="09:00", end_time="10:00"))
        _book(db, user, booking(lab.id, date=d2, start_time="09:00", end_time="10:00"))
        assert _count(db) == 2

    def test_different_lab_same_slot_is_ok(self, db, make_user, make_lab, booking):
        """不同实验室互不影响"""
        user = make_user()
        lab_a = make_lab(name="计算机实验室")
        lab_b = make_lab(name="电子实验室")
        _book(db, user, booking(lab_a.id, start_time="09:00", end_time="10:00"))
        _book(db, user, booking(lab_b.id, start_time="09:00", end_time="10:00"))
        assert _count(db) == 2


class TestLabAndEquipmentAreIndependent:
    """刻意的设计：约设备和约整个实验室互不冲突，两边分开算。

    这条规则写在 backend/data/kb/设备使用.md 里，是给用户的承诺，
    所以要用测试固化下来，防止以后被人"顺手修掉"。
    """

    def test_equipment_booking_does_not_block_lab_booking(
        self, db, make_user, make_lab, make_equipment, booking
    ):
        user, lab = make_user(), make_lab()
        eq = make_equipment(lab.id, name="RTX4090")
        _book(db, user, booking(lab.id, equipment_id=eq.id))
        _book(db, user, booking(lab.id, equipment_id=None))  # 约整间实验室
        assert _count(db) == 2

    def test_lab_booking_does_not_block_equipment_booking(
        self, db, make_user, make_lab, make_equipment, booking
    ):
        user, lab = make_user(), make_lab()
        eq = make_equipment(lab.id, name="RTX4090")
        _book(db, user, booking(lab.id, equipment_id=None))  # 先约整间实验室
        _book(db, user, booking(lab.id, equipment_id=eq.id))
        assert _count(db) == 2

    def test_same_equipment_conflicts(
        self, db, make_user, make_lab, make_equipment, booking
    ):
        """同一台设备、同一时段，才是真冲突"""
        user, lab = make_user(), make_lab()
        eq = make_equipment(lab.id, name="RTX4090")
        _book(db, user, booking(lab.id, equipment_id=eq.id, start_time="09:00", end_time="10:00"))
        with pytest.raises(BusinessException, match="实验室已被预约"):
            _book(db, user, booking(lab.id, equipment_id=eq.id, start_time="09:30", end_time="10:30"))
        assert _count(db) == 1

    def test_different_equipment_does_not_conflict(
        self, db, make_user, make_lab, make_equipment, booking
    ):
        """同一间实验室里的两台不同设备，互不影响"""
        user, lab = make_user(), make_lab()
        eq1 = make_equipment(lab.id, name="RTX4090")
        eq2 = make_equipment(lab.id, name="示波器")
        _book(db, user, booking(lab.id, equipment_id=eq1.id))
        _book(db, user, booking(lab.id, equipment_id=eq2.id))
        assert _count(db) == 2


class TestStatusAffectsOccupancy:
    """只有「待审核(0)」和「已通过(1)」占位；已拒绝(2)、已取消(3)不占位"""

    def _book_then_set_status(self, db, user, request, status):
        _book(db, user, request)
        item = db.query(Reservation).order_by(Reservation.id.desc()).first()
        item.status = status
        db.commit()
        return item

    @pytest.mark.parametrize("status", [2, 3])
    def test_inactive_status_frees_the_slot(
        self, db, make_user, make_lab, booking, status
    ):
        user, lab = make_user(), make_lab()
        self._book_then_set_status(
            db, user, booking(lab.id, start_time="09:00", end_time="10:00"), status
        )
        _book(db, user, booking(lab.id, start_time="09:00", end_time="10:00"))
        assert _count(db) == 2

    @pytest.mark.parametrize("status", [0, 1])
    def test_active_status_keeps_the_slot(
        self, db, make_user, make_lab, booking, status
    ):
        user, lab = make_user(), make_lab()
        self._book_then_set_status(
            db, user, booking(lab.id, start_time="09:00", end_time="10:00"), status
        )
        with pytest.raises(BusinessException, match="实验室已被预约"):
            _book(db, user, booking(lab.id, start_time="09:00", end_time="10:00"))


class TestValidation:
    """预约前的各项校验"""

    def test_past_date_rejected(self, db, make_user, make_lab, booking):
        user, lab = make_user(), make_lab()
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        with pytest.raises(BusinessException, match="预约日期不能早于当前日期"):
            _book(db, user, booking(lab.id, date=yesterday))

    def test_end_before_start_rejected(self, db, make_user, make_lab, booking):
        user, lab = make_user(), make_lab()
        with pytest.raises(BusinessException, match="结束时间不能早于开始时间"):
            _book(db, user, booking(lab.id, start_time="11:00", end_time="09:00"))

    def test_today_with_past_time_rejected(self, db, make_user, make_lab, booking):
        user, lab = make_user(), make_lab()
        today = datetime.now().strftime("%Y-%m-%d")
        with pytest.raises(BusinessException, match="不能早于当前时间"):
            _book(db, user, booking(lab.id, date=today, start_time="00:00", end_time="00:30"))

    def test_unknown_lab_rejected(self, db, make_user, booking):
        user = make_user()
        with pytest.raises(BusinessException, match="实验室不存在"):
            _book(db, user, booking(999999))

    def test_closed_lab_rejected(self, db, make_user, make_lab, booking):
        user, lab = make_user(), make_lab(status=0)
        with pytest.raises(BusinessException, match="实验室未开放预约"):
            _book(db, user, booking(lab.id))

    def test_before_open_time_rejected(self, db, make_user, make_lab, booking):
        user, lab = make_user(), make_lab(open_time="08:00")
        with pytest.raises(BusinessException, match="不能早于实验室开放时间"):
            _book(db, user, booking(lab.id, start_time="07:00", end_time="08:00"))

    def test_after_close_time_rejected(self, db, make_user, make_lab, booking):
        user, lab = make_user(), make_lab(close_time="18:00")
        with pytest.raises(BusinessException, match="不能晚于实验室关闭时间"):
            _book(db, user, booking(lab.id, start_time="18:00", end_time="19:00"))

    def test_unknown_equipment_rejected(self, db, make_user, make_lab, booking):
        user, lab = make_user(), make_lab()
        with pytest.raises(BusinessException, match="实验室设备不存在"):
            _book(db, user, booking(lab.id, equipment_id=999999))

    def test_equipment_under_repair_rejected(
        self, db, make_user, make_lab, make_equipment, booking
    ):
        user, lab = make_user(), make_lab()
        eq = make_equipment(lab.id, status=0)
        with pytest.raises(BusinessException, match="正在维修"):
            _book(db, user, booking(lab.id, equipment_id=eq.id))
