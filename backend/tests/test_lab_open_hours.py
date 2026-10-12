"""开放时间分周中/周末两套之后的回归用例。

核心是：**「某一天该用哪套时段」只由 `lab_service.resolve_open_hours` 判断**，
预约校验、空闲时段查询、AI 工具、界面显示全部从它派生。
以前这套规则只写在知识库的 md 里、代码完全没实现，而数据库里那份又跟它
对不上（覆盖的实验室数、计算机实验室的关门时间都不同）。

时间一律钉死再断言，不靠系统时钟。要钉的入口是 `lab_service._now`。

AI 那一层的用例在 test_agent_open_hours.py。
"""

from datetime import datetime, timedelta

import pytest

from app.common.exceptions import BusinessException
from app.models.lab import Lab
from app.models.reservation import Reservation
from app.services import lab_service, reservation_service

# datetime.weekday() 的编号：周一 0 …… 周六 5、周日 6
WEDNESDAY = 2
SATURDAY = 5
SUNDAY = 6


def _next_weekday(weekday: int) -> str:
    """往后（至少明天）找第一个星期几，返回 YYYY-MM-DD。

    从明天起步是为了避开两条跟"今天"有关的校验——"预约日期不能早于当前日期"
    和"不能查询过去的日期"。最多找 7 天，一定找得到。
    """
    day = datetime.now() + timedelta(days=1)
    for _ in range(7):
        if day.weekday() == weekday:
            return day.strftime("%Y-%m-%d")
        day += timedelta(days=1)
    raise AssertionError(f"往后 7 天里没有 weekday={weekday}")


def _at(date: str, time: str) -> datetime:
    return datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")


def _lab(**overrides) -> Lab:
    """造一个**不落库**的 Lab，只用来试 resolve_open_hours / is_open_at 的取值。

    这两个是纯函数，只读属性，不需要真进数据库；这样才能顺手造出
    「周末两列是 NULL」这种 make_lab 夹具造不出来的组合——夹具里的
    None 表示"跟周中一样"，是刻意的好默认值，但测不了 NULL 本身。
    """
    fields = dict(
        name="计算机实验室",
        capacity=40,
        status=1,
        open_time="08:00",
        close_time="20:00",
        weekend_open_time=None,
        weekend_close_time=None,
    )
    fields.update(overrides)
    return Lab(**fields)


class TestResolveOpenHours:
    """哪一天用哪套时段，全项目只有这一个判断点。"""

    def test_weekday_uses_weekday_hours(self):
        lab = _lab(
            open_time="08:00",
            close_time="20:00",
            weekend_open_time="09:00",
            weekend_close_time="17:00",
        )
        assert lab_service.resolve_open_hours(lab, _next_weekday(WEDNESDAY)) == (
            "08:00",
            "20:00",
        )

    def test_saturday_uses_weekend_hours(self):
        lab = _lab(
            open_time="08:00",
            close_time="20:00",
            weekend_open_time="09:00",
            weekend_close_time="17:00",
        )
        assert lab_service.resolve_open_hours(lab, _next_weekday(SATURDAY)) == (
            "09:00",
            "17:00",
        )

    def test_sunday_counts_as_weekend_too(self):
        lab = _lab(
            weekend_open_time="09:00",
            weekend_close_time="17:00",
        )
        assert lab_service.resolve_open_hours(lab, _next_weekday(SUNDAY)) == (
            "09:00",
            "17:00",
        )

    def test_null_and_empty_string_mean_the_same(self):
        """周末两列不管写 NULL 还是空字符串，都算"周末不开放"。

        空字符串是管理端表单的产物：把时间选择器清空，发上来的是 ''，不是 null。
        只认 None 的话，管理员一旦填过周末时段，就再也改不回"不开放"了——
        更新接口是部分更新，'' 会被原样存进去，判断永远不命中。
        """
        saturday = _next_weekday(SATURDAY)
        assert lab_service.resolve_open_hours(
            _lab(weekend_open_time=None, weekend_close_time=None), saturday
        ) == (None, None)
        assert lab_service.resolve_open_hours(
            _lab(weekend_open_time="", weekend_close_time=""), saturday
        ) == (None, None)

    def test_weekday_hours_unset_means_closed(self):
        """周中时段没设也一样：没设 = 那天不开放，不是"随便约"。"""
        lab = _lab(open_time=None, close_time=None)
        assert lab_service.resolve_open_hours(lab, _next_weekday(WEDNESDAY)) == (
            None,
            None,
        )


class TestIsOpenAt:
    """"此刻开着没"。"""

    def test_boundaries_are_inclusive(self):
        """开门和关门那两个整点都算开放。

        跟预约校验的边界保持一致（那边是 start < 开门 或 end > 关门 才拒绝）。
        不一致的话，20:00 整那一刻会出现"界面说开着、下单说关了"。
        """
        lab = _lab(open_time="08:00", close_time="20:00")
        day = _next_weekday(WEDNESDAY)
        assert lab_service.is_open_at(lab, _at(day, "08:00")) is True
        assert lab_service.is_open_at(lab, _at(day, "20:00")) is True
        assert lab_service.is_open_at(lab, _at(day, "07:59")) is False
        assert lab_service.is_open_at(lab, _at(day, "20:01")) is False

    def test_disabled_lab_is_never_open(self):
        """被停用的实验室，哪怕正处在时段里也不算开放。

        少了这条，界面会对一间根本约不上的实验室显示"开放中"——
        预约那边可是会拿 status 拒人的。
        """
        lab = _lab(status=0, open_time="00:00", close_time="23:59")
        assert lab_service.is_open_at(lab, _at(_next_weekday(WEDNESDAY), "10:00")) is False

    def test_closed_day_is_not_open(self):
        lab = _lab(weekend_open_time="", weekend_close_time="")
        assert lab_service.is_open_at(lab, _at(_next_weekday(SATURDAY), "10:00")) is False

    def test_weekend_hours_apply_on_saturday(self):
        lab = _lab(
            open_time="08:00",
            close_time="20:00",
            weekend_open_time="09:00",
            weekend_close_time="17:00",
        )
        saturday = _next_weekday(SATURDAY)
        assert lab_service.is_open_at(lab, _at(saturday, "10:00")) is True
        # 周六 08:30：周中这个点已经开门了，周末还没到——周末那套确实生效了
        assert lab_service.is_open_at(lab, _at(saturday, "08:30")) is False
        assert lab_service.is_open_at(lab, _at(saturday, "17:30")) is False


class TestToLabResponse:
    """给界面和 AI 用的那三个计算字段。"""

    def test_today_hours_and_open_now_follow_the_given_time(self, make_lab):
        lab = make_lab(
            open_time="08:00",
            close_time="20:00",
            weekend_open_time="09:00",
            weekend_close_time="17:00",
        )
        saturday = _next_weekday(SATURDAY)

        res = lab_service.to_lab_response(lab, _at(saturday, "10:00"))
        assert (res.today_open_time, res.today_close_time) == ("09:00", "17:00")
        assert res.open_now is True

        res = lab_service.to_lab_response(lab, _at(saturday, "18:00"))
        assert (res.today_open_time, res.today_close_time) == ("09:00", "17:00")
        assert res.open_now is False

    def test_closed_day_reports_no_hours(self, make_lab):
        lab = make_lab(weekend_open_time="", weekend_close_time="")
        res = lab_service.to_lab_response(lab, _at(_next_weekday(SATURDAY), "10:00"))
        assert res.today_open_time is None
        assert res.today_close_time is None
        assert res.open_now is False

    def test_weekday_fields_still_exposed(self, make_lab):
        """周中和周末两套都要给出来——管理端表单要回填，AI 要能解释为什么。"""
        lab = make_lab(
            open_time="08:00",
            close_time="20:00",
            weekend_open_time="09:00",
            weekend_close_time="17:00",
        )
        res = lab_service.to_lab_response(lab, _at(_next_weekday(WEDNESDAY), "10:00"))
        assert (res.open_time, res.close_time) == ("08:00", "20:00")
        assert (res.weekend_open_time, res.weekend_close_time) == ("09:00", "17:00")


class TestWeekendReservation:
    """预约校验必须按"预约的那一天"取时段。"""

    def test_closed_weekend_rejected(self, db, make_user, make_lab, booking):
        lab = make_lab(weekend_open_time="", weekend_close_time="")
        user = make_user()

        with pytest.raises(BusinessException, match="该实验室当天不开放"):
            reservation_service.create_reservation(
                db,
                user,
                booking(
                    lab.id,
                    date=_next_weekday(SATURDAY),
                    start_time="10:00",
                    end_time="11:00",
                ),
            )
        assert db.query(Reservation).count() == 0

    def test_weekend_hours_are_enforced(self, db, make_user, make_lab, booking):
        """周六只开 09:00-17:00：08:00 还没开门，10:00 正常。"""
        lab = make_lab(
            open_time="08:00",
            close_time="20:00",
            weekend_open_time="09:00",
            weekend_close_time="17:00",
        )
        user = make_user()
        saturday = _next_weekday(SATURDAY)

        with pytest.raises(BusinessException, match="不能早于实验室开放时间"):
            reservation_service.create_reservation(
                db,
                user,
                booking(lab.id, date=saturday, start_time="08:00", end_time="09:00"),
            )

        reservation_service.create_reservation(
            db,
            user,
            booking(lab.id, date=saturday, start_time="10:00", end_time="11:00"),
        )
        assert db.query(Reservation).count() == 1

    def test_weekday_hours_still_apply_on_weekdays(
        self, db, make_user, make_lab, booking
    ):
        """别拦过头：周末那两列留空，不该影响周一。"""
        lab = make_lab(
            open_time="08:00",
            close_time="20:00",
            weekend_open_time="",
            weekend_close_time="",
        )
        reservation_service.create_reservation(
            db,
            make_user(),
            booking(
                lab.id,
                date=_next_weekday(WEDNESDAY),
                start_time="10:00",
                end_time="11:00",
            ),
        )
        assert db.query(Reservation).count() == 1


class TestFreeSlotsUsesTheDay:
    """空闲时段查询跟预约校验得用同一套时段，否则一边拦得住、一边列出一整天。"""

    def test_closed_day_rejected(self, db, make_lab):
        lab = make_lab(weekend_open_time="", weekend_close_time="")

        with pytest.raises(BusinessException, match="该实验室当天不开放"):
            reservation_service.get_free_slots(db, lab.id, _next_weekday(SATURDAY))

    def test_weekend_hours_reported(self, db, make_lab):
        lab = make_lab(
            open_time="08:00",
            close_time="20:00",
            weekend_open_time="09:00",
            weekend_close_time="17:00",
        )
        res = reservation_service.get_free_slots(db, lab.id, _next_weekday(SATURDAY))

        assert (res.open_time, res.close_time) == ("09:00", "17:00")
        # 空闲时段必须落在周末那套时段之内，不能漏出 08:00 这种周中才有的点
        assert all(slot.start_time >= "09:00" for slot in res.slots)
        assert all(slot.end_time <= "17:00" for slot in res.slots)

    def test_equipment_ownership_checked_before_closed_day(
        self, db, make_lab, make_equipment
    ):
        """两条错误都成立时报哪条？报设备归属。

        用户实际搞错的是"哪台设备"，说"当天不开放"会把他引到错误的路上。
        这条顺手钉住了两个判断的先后顺序——后来谁把"不开放"挪到前面就会红。
        """
        owner = make_lab(name="计算机实验室")
        other = make_lab(
            name="电子实验室", weekend_open_time="", weekend_close_time=""
        )
        equipment = make_equipment(lab_id=owner.id)

        with pytest.raises(BusinessException, match="该设备不属于所选实验室"):
            reservation_service.get_free_slots(
                db, other.id, _next_weekday(SATURDAY), equipment.id
            )
