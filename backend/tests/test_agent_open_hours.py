"""AI 工具与提示词的回归用例。

治的是用户报的那个 bug：晚上 21:39 问 AI"现在有哪些实验室开放"，
它答"8 间开放"——那时 8 间实验室的 status 确实都是 1，但早就关门了。
成因有三层，这个文件把后两层钉住：

1. `list_labs`（当时叫 list_open_labs）筛的是 status=1，也就是
   "管理员启用了"，却当成"此刻开放中"报给模型；
2. 提示词里没定义"开放"，也没告诉模型现在几点、今天星期几；
3. 模型沿用上一轮对话里的结论——这条靠提示词里的硬规则治，
   前端组装历史时丢掉工具调用过程是另一回事，这里只守住规则写了没有。

时间一律钉死：`lab_service._now` 是列表页取"现在"的入口。
"""

import json
import re
from datetime import datetime, timedelta

from app.services import lab_service

# datetime.weekday() 的编号：周一 0 …… 周六 5
WEDNESDAY = 2
SATURDAY = 5


def _next_weekday(weekday: int) -> str:
    """往后（至少明天）找第一个星期几，返回 YYYY-MM-DD。

    从明天起步是为了避开跟"今天"有关的校验。最多找 7 天，一定找得到。
    """
    day = datetime.now() + timedelta(days=1)
    for _ in range(7):
        if day.weekday() == weekday:
            return day.strftime("%Y-%m-%d")
        day += timedelta(days=1)
    raise AssertionError(f"往后 7 天里没有 weekday={weekday}")


def _at(date: str, time: str) -> datetime:
    return datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")


def _tool_map(user_id: int) -> dict:
    """{工具名: 工具}，按模型实际会看到的那一套。"""
    from app.services import agent_tools

    return {t.name: t for t in agent_tools.build_tools(user_id)}


class TestListLabs:
    """工具必须把"管理员启用了"和"此刻开着"分开说。"""

    def test_reports_open_now_not_just_enabled(
        self, db, make_user, make_lab, monkeypatch
    ):
        """用户报的那个 bug 本身。

        晚上 22:00，计算机实验室 status=1（管理员启用着）但当天 20:00 就关门了。
        以前工具只筛 status=1 就当作"开放中"报出去，模型于是答"8 间开放"。
        """
        monkeypatch.setattr(
            lab_service, "_now", lambda: _at(_next_weekday(WEDNESDAY), "22:00")
        )
        make_lab(name="计算机实验室", open_time="08:00", close_time="20:00")

        payload = json.loads(_tool_map(make_user().id)["list_labs"].invoke({}))

        row = next(item for item in payload["labs"] if item["name"] == "计算机实验室")
        assert row["enabled"] is True
        assert row["today_hours"] == "08:00-20:00"
        assert row["open_now"] is False

    def test_says_open_when_it_really_is(self, db, make_user, make_lab, monkeypatch):
        """反向也要成立，否则上面那条靠"永远返回 false"也能骗过去。"""
        monkeypatch.setattr(
            lab_service, "_now", lambda: _at(_next_weekday(WEDNESDAY), "10:00")
        )
        make_lab(name="计算机实验室", open_time="08:00", close_time="20:00")

        payload = json.loads(_tool_map(make_user().id)["list_labs"].invoke({}))

        row = next(item for item in payload["labs"] if item["name"] == "计算机实验室")
        assert row["open_now"] is True

    def test_weekend_closed_lab_is_still_listed(
        self, db, make_user, make_lab, monkeypatch
    ):
        """周末不开放的实验室，周六问的时候不能从列表里"消失"。

        它得在，由 today_hours=null 说明今天不开门。直接被筛掉的话，
        模型会答"没有这家实验室"——那是另一种错，而且更难被用户发现。
        """
        monkeypatch.setattr(
            lab_service, "_now", lambda: _at(_next_weekday(SATURDAY), "10:30")
        )
        make_lab(
            name="化学实验室",
            open_time="08:00",
            close_time="18:00",
            weekend_open_time="",
            weekend_close_time="",
        )

        payload = json.loads(_tool_map(make_user().id)["list_labs"].invoke({}))

        row = next(item for item in payload["labs"] if item["name"] == "化学实验室")
        assert row["enabled"] is True
        assert row["weekday_hours"] == "08:00-18:00"
        assert row["today_hours"] is None
        assert row["open_now"] is False

    def test_disabled_lab_is_listed_with_enabled_false(self, db, make_user, make_lab):
        """停用的实验室也要在列表里，由 enabled 说明情况。

        以前这个工具固定筛 status=1，名字却叫"开放中的实验室"——
        "没启用"和"此刻没开"就是这么混成一件事的。
        """
        make_lab(name="停用中的实验室", status=0)

        payload = json.loads(_tool_map(make_user().id)["list_labs"].invoke({}))

        row = next(item for item in payload["labs"] if item["name"] == "停用中的实验室")
        assert row["enabled"] is False
        assert row["open_now"] is False

    def test_nothing_open_at_night(self, db, make_user, make_lab, monkeypatch):
        """把用户那一问原样重演一遍：晚上问"有几间开着"，答案是 0 间。

        8 间实验室、全部启用、全部有周中时段——这就是他当时的库。
        """
        monkeypatch.setattr(
            lab_service, "_now", lambda: _at(_next_weekday(WEDNESDAY), "21:39")
        )
        for i in range(8):
            make_lab(name=f"实验室{i}", open_time="08:00", close_time="20:00")

        payload = json.loads(_tool_map(make_user().id)["list_labs"].invoke({}))

        assert payload["total"] == 8
        assert sum(item["open_now"] for item in payload["labs"]) == 0


class TestGetToday:
    def test_carries_weekday_and_time(self, db, make_user):
        """光有日期不够：时段分周中/周末两套，判不出星期几就用不对那一套。"""
        payload = json.loads(_tool_map(make_user().id)["get_today"].invoke({}))

        day = datetime.strptime(payload["date"], "%Y-%m-%d")
        assert payload["weekday"] == lab_service.WEEKDAY_NAMES[day.weekday()]
        assert payload["is_weekend"] is (day.weekday() in lab_service.WEEKEND_DAYS)
        assert re.fullmatch(r"\d{2}:\d{2}", payload["time"])


class TestAgentWiring:
    """改了名忘了改别处。这类错原先一条测试都拦不住。"""

    def test_every_tool_has_a_label(self, db, make_user):
        """工具名和前端显示的中文名必须一一对应。

        对不上时前端走 `TOOL_LABELS.get(name, name)` 的兜底，
        把英文工具名直接显示给用户。
        """
        from app.services import agent_service

        tools = {t.name for t in _tool_map(make_user().id).values()}
        assert tools == set(agent_service.TOOL_LABELS)

    def test_prompt_only_names_real_tools_and_fields(self, db, make_user, make_lab):
        """提示词里那些带下划线的词，必须真的是工具名、参数名或返回体字段名。

        写死一份清单的话，改一次名字就得来改测试；这里全部从真实对象现取，
        所以它拦的是"提示词在指使模型调用一个不存在的东西"——
        比如把 list_open_labs 改名成 list_labs 时漏改了提示词里的一处。
        """
        from app.services import agent_service

        make_lab(name="计算机实验室")
        tools = _tool_map(make_user().id)

        known = set(tools)
        for tool in tools.values():
            known |= set(tool.args)  # 参数名，比如 lab_id / equipment_id
        known |= set(json.loads(tools["list_labs"].invoke({}))["labs"][0])
        known |= set(json.loads(tools["get_today"].invoke({})))

        mentioned = set(
            re.findall(
                r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", agent_service.SYSTEM_PROMPT
            )
        )
        unknown = sorted(mentioned - known)
        assert not unknown, (
            f"提示词里提到了不存在的东西：{unknown}。"
            "要么是工具/字段改了名却漏改提示词，要么是提示词在让模型调一个不存在的工具。"
        )

    def test_system_prompt_carries_the_current_time(self):
        """当前时间必须真拼进去。

        模型自己不知道"现在几点、今天星期几"，不给它这个信息，
        "现在哪些实验室开着"就只能靠猜。
        """
        from app.services import agent_service

        stamp = _at(_next_weekday(WEDNESDAY), "21:39")
        text = agent_service.build_system_prompt(stamp)

        assert lab_service.describe_moment(stamp) in text
        # 占位符没被替换掉的话，模型看到的是字面量 "{now}"
        assert "{now}" not in text
        assert "{now}" not in agent_service.build_system_prompt()

    def test_prompt_defines_open_and_forbids_stale_answers(self):
        """两条硬规则得真在提示词里。

        "开放"得有定义，否则模型按"管理员启用了"理解（这正是那个 bug）。
        还得明确禁止沿用旧结论：前端组装历史时丢掉了工具调用过程，
        模型手上没有依据，不说清楚它就会把自己上一条错话重复一遍。
        """
        from app.services import agent_service

        prompt = agent_service.SYSTEM_PROMPT
        assert "open_now" in prompt
        assert "重新调用工具" in prompt
        assert "以这一轮查到的为准" in prompt
