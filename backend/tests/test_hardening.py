"""P1 后端加固的回归用例。

这里钉的都是「输入即攻击面」那一类问题——全部能被外部请求直接触发，
不是理论风险。每条对应一处具体修改：

    A1  时间字段规范化      -> TestTimeNormalization / TestFreeSlotsDateValidation
    A2  设备归属校验        -> TestEquipmentOwnership
    A2r 设备冲突范围        -> TestEquipmentConflictScope
    A3  上传接口鉴权        -> TestUploadAuth
    A4  登录/注册限流       -> TestAuthRateLimit
    A5  AI 入参上界         -> TestChatInputBounds
    A5b AI 单条/总量上界    -> TestChatContentCaps
    A5c 对话接口限流        -> TestChatRateLimit
    A6  分页上界            -> TestPaginationBounds
    A6b 实验室状态筛选      -> TestLabListStatusFilter
    A7  个人资料部分更新    -> TestPartialProfileUpdate
    A8  字符串长度上限      -> TestStringFieldLengthCaps
    B2  工具异常不泄漏原文  -> TestToolErrorMasking
"""

import json
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.common.exceptions import BusinessException
from app.models.reservation import Reservation
from app.schemas.ai import ChatMessage, ChatRequest
from app.schemas.auth import RegisterRequest
from app.schemas.lab import LabCreateRequest
from app.schemas.reservation import (
    ReservationCreateRequest,
    normalize_date,
    normalize_time,
)
from app.schemas.user import UserUpdateRequest
from app.services import reservation_service, user_service
from app.services.agent_service import _build_history

LOGIN = "/api/auth/login"
REGISTER = "/api/auth/register"
UPLOAD = "/api/files/upload"
CHAT_STREAM = "/api/ai/chat/stream"

# 四个带分页的列表接口。user 那个要管理员，所以统一用管理员身份打。
LIST_ENDPOINTS = [
    "/api/lab/list",
    "/api/equipment/list",
    "/api/user/list",
    "/api/reservation/list",
]


def _tomorrow() -> str:
    return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


def _next_unpadded_date() -> datetime:
    """往后找一个「不补零写法 ≠ 补零写法」的日期。

    要验 normalize_date 真的做了归一，就得让输入和输出长得不一样。
    直接拿「明天」是不行的：明天正好是两位月两位日时（比如 10-10），
    f"{y}-{m}-{d}" 跟 strftime 的结果完全相同，用例就退化成恒真——
    把 normalize_date 换成恒等函数它照样绿。
    一个月之内必然出现单个数字的月或日，找不到就是这儿写错了。
    """
    for offset in range(1, 33):
        day = datetime.now() + timedelta(days=offset)
        if f"{day.year}-{day.month}-{day.day}" != day.strftime("%Y-%m-%d"):
            return day
    raise AssertionError("往后一个月内没找到不补零的日期，日期构造逻辑有问题")


class TestTimeNormalization:
    """A1：时间必须补零，否则字符串比较会漏判重叠"""

    def test_unpadded_time_is_normalized(self):
        req = ReservationCreateRequest(
            lab_id=1, date="2026-10-09", start_time="9:00", end_time="10:00"
        )
        assert req.start_time == "09:00"
        assert req.end_time == "10:00"

    def test_unpadded_date_is_normalized(self):
        assert normalize_date("2026-10-9") == "2026-10-09"

    def test_unpadded_booking_still_collides(self, db, make_user, make_lab, booking):
        """这条缺陷的核心。

        修好之前 "9:00" 和 "09:00" 在字典序里是两个不同的值：
        "09:30" > "9:00" 为假，重叠判定漏判，同一时段能被约两次。
        """
        user, lab = make_user(), make_lab()
        reservation_service.create_reservation(
            db, user, booking(lab.id, start_time="09:00", end_time="09:30")
        )
        with pytest.raises(BusinessException, match="实验室已被预约"):
            reservation_service.create_reservation(
                db, user, booking(lab.id, start_time="9:00", end_time="9:30")
            )
        assert db.query(Reservation).count() == 1

    @pytest.mark.parametrize("bad", ["2026/10/09", "abc", "2026-13-01", ""])
    def test_bad_date_rejected(self, bad):
        with pytest.raises(ValueError):
            normalize_date(bad)

    @pytest.mark.parametrize("bad", ["9点", "25:00", "09:60", "", "0900"])
    def test_bad_time_rejected(self, bad):
        with pytest.raises(ValueError):
            normalize_time(bad)

    def test_schema_rejects_malformed_input(self):
        with pytest.raises(ValidationError):
            ReservationCreateRequest(
                lab_id=1, date="2026-10-09", start_time="morning", end_time="10:00"
            )


class TestFreeSlotsDateValidation:
    """A1 第二半：get_free_slots 没有路由层兜底，date 是模型直接给的"""

    def test_bad_date_rejected(self, db, make_lab):
        lab = make_lab()
        with pytest.raises(BusinessException, match="日期格式"):
            reservation_service.get_free_slots(db, lab.id, "abc")

    def test_unpadded_date_accepted_and_normalized(self, db, make_lab):
        lab = make_lab()
        target = _next_unpadded_date()
        # 故意不补零：str(int) 不会带前导零
        unpadded = f"{target.year}-{target.month}-{target.day}"
        # 先把「这条输入确实没补零」钉死。少了这句，哪天 target 落到 10-10
        # 这种日期上，下面那个断言就又变成拿补零值比补零值了。
        assert unpadded != target.strftime("%Y-%m-%d")
        res = reservation_service.get_free_slots(db, lab.id, unpadded)
        assert res.date == target.strftime("%Y-%m-%d")


class TestEquipmentOwnership:
    """A2：设备必须属于所选实验室，否则冲突检测会漏判"""

    def test_booking_foreign_equipment_rejected(
        self, db, make_user, make_lab, make_equipment, booking
    ):
        lab_a, lab_b = make_lab(name="A"), make_lab(name="B")
        foreign = make_equipment(lab_id=lab_b.id)

        with pytest.raises(BusinessException, match="不属于所选实验室"):
            reservation_service.create_reservation(
                db, make_user(), booking(lab_a.id, equipment_id=foreign.id)
            )
        assert db.query(Reservation).count() == 0

    def test_free_slots_foreign_equipment_rejected(self, db, make_lab, make_equipment):
        lab_a, lab_b = make_lab(name="A"), make_lab(name="B")
        foreign = make_equipment(lab_id=lab_b.id)

        with pytest.raises(BusinessException, match="不属于所选实验室"):
            reservation_service.get_free_slots(db, lab_a.id, _tomorrow(), foreign.id)

    def test_own_equipment_still_bookable(
        self, db, make_user, make_lab, make_equipment, booking
    ):
        """补上归属校验别把正常路径一起挡了"""
        lab = make_lab()
        eq = make_equipment(lab_id=lab.id)
        reservation_service.create_reservation(
            db, make_user(), booking(lab.id, equipment_id=eq.id)
        )
        assert db.query(Reservation).count() == 1


class TestUploadAuth:
    """A3：上传接口以前是匿名可用的"""

    def test_anonymous_upload_rejected(self, client):
        resp = client.post(
            UPLOAD, files={"file": ("a.png", b"\x89PNG\r\n\x1a\n", "image/png")}
        )
        assert resp.status_code == 401

    def test_logged_in_upload_allowed(self, client, make_user, auth_headers):
        from app.config import UPLOAD_DIR

        user = make_user()
        resp = client.post(
            UPLOAD,
            headers=auth_headers(user),
            files={"file": ("tiny.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        )
        body = resp.json()
        assert body["code"] == 200
        # 测试产生的文件不要留在 uploads/ 里
        (UPLOAD_DIR / body["data"]["disk_name"]).unlink(missing_ok=True)


class TestAuthRateLimit:
    """A4：登录与注册是全后端仅有的两个「未鉴权但跑 bcrypt」的入口"""

    def test_login_is_rate_limited(self, client, make_user):
        make_user(username="alice", password="pw123456")
        payload = {"username": "alice", "password": "wrong"}
        codes = [client.post(LOGIN, json=payload).status_code for _ in range(6)]

        assert codes[:5] == [200] * 5, "前 5 次应当正常走到业务逻辑"
        assert codes[5] == 429, "第 6 次必须被限流挡下"

    def test_rate_limit_body_uses_project_envelope(self, client, make_user):
        """429 是全项目唯一不走 HTTP 200 的地方，body 仍然要合项目规范"""
        make_user(username="alice", password="pw123456")
        payload = {"username": "alice", "password": "wrong"}
        for _ in range(5):
            client.post(LOGIN, json=payload)
        body = client.post(LOGIN, json=payload).json()
        assert body["code"] == 429
        assert body["message"]

    def test_register_is_rate_limited(self, client):
        codes = [
            client.post(
                REGISTER, json={"username": f"u{i}", "password": "pw123456"}
            ).status_code
            for i in range(6)
        ]
        assert codes[5] == 429

    def test_limiter_does_not_leak_across_tests(self, client, make_user):
        """conftest 的 _reset_rate_limiter 要在用例间把计数清掉。

        没有它的话上面几个用例会把额度耗光，这里第一次登录就吃 429。
        """
        make_user(username="alice", password="pw123456")
        resp = client.post(LOGIN, json={"username": "alice", "password": "pw123456"})
        assert resp.status_code == 200


class TestChatInputBounds:
    """A5：AI 入参以前完全没有上界"""

    def test_too_many_messages_rejected(self):
        msg = ChatMessage(role="user", content="你好")
        with pytest.raises(ValidationError):
            ChatRequest(messages=[msg] * 101)

    def test_overlong_content_rejected(self):
        with pytest.raises(ValidationError):
            ChatMessage(role="user", content="字" * 2001)

    def test_empty_content_rejected(self):
        with pytest.raises(ValidationError):
            ChatMessage(role="user", content="")

    def test_unknown_role_rejected(self):
        with pytest.raises(ValidationError):
            ChatMessage(role="system", content="你好")

    def test_empty_message_list_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(messages=[])

    def test_message_count_boundary_accepted(self):
        """边界值本身要放行，别把上限做成了排他"""
        ChatRequest(messages=[ChatMessage(role="user", content="你好")] * 100)

    def test_content_length_boundary_accepted(self):
        ChatMessage(role="user", content="字" * 2000)

    def test_count_and_length_at_the_same_time(self):
        """条数和字长同时顶满会撞上请求体总量上界，所以压在上界上的组合是 50 × 2000"""
        ChatRequest(messages=[ChatMessage(role="user", content="字" * 2000)] * 50)


class TestChatHistoryTrim:
    """请求条数有硬上限（挡滥用），但送进模型的上下文靠截断而非拒收。

    这条是第一版改动的回归：schema 上写死 max_length=20，
    而前端传的是整段对话历史，结果聊到第 21 条整个对话就发不出去。
    """

    def test_21_messages_no_longer_breaks_the_chat(self):
        msgs = [ChatMessage(role="user", content=f"第{i}条") for i in range(21)]
        ChatRequest(messages=msgs)  # 不应抛异常

    def test_long_conversation_is_trimmed(self):
        msgs = [
            ChatMessage(
                role="user" if i % 2 == 0 else "assistant", content=f"第{i}条"
            )
            for i in range(60)
        ]
        history = _build_history(ChatRequest(messages=msgs))
        assert len(history) == 20, "进模型的条数必须有界"
        assert history[-1].content == "第59条", "要保留最近的，不是最早的"

    def test_short_conversation_untouched(self):
        msgs = [
            ChatMessage(role="user", content="你好"),
            ChatMessage(role="assistant", content="您好"),
        ]
        assert len(_build_history(ChatRequest(messages=msgs))) == 2

    def test_trim_counts_only_non_empty_messages(self):
        """空白消息先被过滤，截断的 20 条指的是真正进模型的那个数"""
        msgs = [ChatMessage(role="user", content=" ")] * 5
        msgs += [ChatMessage(role="user", content=f"第{i}条") for i in range(30)]
        history = _build_history(ChatRequest(messages=msgs))
        assert len(history) == 20


class TestPartialProfileUpdate:
    """A7：PUT /user/me 以前会把没传的字段写成 NULL"""

    def test_partial_update_keeps_other_fields(self, db, make_user):
        user = make_user(username="alice")
        user.email = "alice@example.com"
        user.phone = "13800000000"
        db.commit()

        user_service.update_user_info(db, user, UserUpdateRequest(phone="13900000000"))

        db.refresh(user)
        assert user.phone == "13900000000"
        assert user.name == "alice", "没传的字段不能被清空"
        assert user.email == "alice@example.com"

    def test_single_field_update_does_not_error(self, db, make_user):
        """只传一个字段以前会让 name 撞 NOT NULL 直接 500"""
        user = make_user(username="alice")
        user_service.update_user_info(db, user, UserUpdateRequest(email="a@b.com"))
        db.refresh(user)
        assert user.email == "a@b.com"
        assert user.name == "alice"

    def test_role_still_cannot_be_escalated(self, db, make_user):
        """A7 换了写法，但提权防护不能跟着丢"""
        user = make_user(username="alice", role="student")
        user_service.update_user_info(
            db, user, UserUpdateRequest(name="改名了", role="admin")
        )
        db.refresh(user)
        assert user.name == "改名了"
        assert user.role == "student"


class TestToolErrorMasking:
    """B2：工具异常原文会经 SSE 的 tool_end 预览送到前端"""

    def test_tool_failed_returns_fixed_message(self):
        from app.services.agent_tools import _tool_failed

        payload = json.loads(_tool_failed("search_lab_docs"))
        assert payload["ok"] is False
        assert payload["error"] == "操作失败，请稍后重试"

    def test_search_tool_masks_internal_error(self, db, make_user, monkeypatch):
        from app.services import agent_tools, kb_service

        def boom(_query):
            raise RuntimeError("SELECT * FROM users WHERE password='hunter2'")

        monkeypatch.setattr(kb_service, "search", boom)
        tools = {t.name: t for t in agent_tools.build_tools(db, make_user())}
        result = json.loads(tools["search_lab_docs"].invoke("随便问点什么"))

        assert result["ok"] is False
        assert "hunter2" not in result["error"], "不能把绑定参数带出去"
        assert "SELECT" not in result["error"], "不能把 SQL 语句带出去"

    def test_agent_validation_error_gives_actionable_hint(self, db, make_user):
        """A1 加了格式校验后，模型传错格式要能拿到可自我纠正的提示。

        不能让它被通用兜底吞成一句笼统的失败——那样模型就失去了重试的线索。
        """
        from app.services import agent_tools

        tools = {t.name: t for t in agent_tools.build_tools(db, make_user())}
        result = json.loads(
            tools["create_lab_reservation"].invoke(
                {
                    "lab_id": 1,
                    "date": "明天",
                    "start_time": "09:00",
                    "end_time": "10:00",
                }
            )
        )
        assert result["ok"] is False
        assert "YYYY-MM-DD" in result["error"]


class TestChatContentCaps:
    """A5b：单条消息按角色分档卡长度，整个请求体另有总量上界。

    单条上限是为了挡滥用，但不能把正常对话卡死：助手那侧回显的是我们自己
    产出的内容（markdown 列表、表格），比用户手打的输入长是正常的。
    两头都卡 2000 的话，只要某轮回复长一点，之后每一次请求都会吃 422，
    对话就永久发不出去了——跟当初 max_length=20 那个 bug 是同一个坑。
    """

    def test_assistant_content_may_exceed_the_user_limit(self):
        ChatMessage(role="assistant", content="字" * 3000)

    def test_assistant_content_still_capped(self):
        with pytest.raises(ValidationError):
            ChatMessage(role="assistant", content="字" * 4001)

    def test_total_content_capped(self):
        """只卡条数不够：100 × 4000 还是能拼出一个 1MB 级的请求体"""
        msg = ChatMessage(role="user", content="字" * 2000)
        with pytest.raises(ValidationError):
            ChatRequest(messages=[msg] * 51)


class TestChatRateLimit:
    """A5c：/ai/chat/stream 每问一次就是一次真实的大模型调用。

    不限流的话一个脚本就能把额度刷干，比登录撞库贵得多。
    """

    def test_chat_stream_is_rate_limited(
        self, client, make_user, auth_headers, monkeypatch
    ):
        from app.services import agent_service

        # 只验限流本身，不去真调模型：把 SSE 生成器换成一个空实现。
        async def fake_stream(db, current_user, data):
            yield {"type": "done"}

        monkeypatch.setattr(agent_service, "stream_agent", fake_stream)

        headers = auth_headers(make_user())
        body = {"messages": [{"role": "user", "content": "你好"}]}
        codes = [
            client.post(CHAT_STREAM, json=body, headers=headers).status_code
            for _ in range(21)
        ]
        assert codes[:20] == [200] * 20, "前 20 次应当正常走到业务逻辑"
        assert codes[20] == 429, "第 21 次必须被限流挡下"


class TestPaginationBounds:
    """A6：分页参数直接进 LIMIT/OFFSET，不设上界等于把全表读开放给任何登录用户"""

    @pytest.mark.parametrize("path", LIST_ENDPOINTS)
    def test_oversized_page_size_rejected(self, client, make_user, auth_headers, path):
        headers = auth_headers(make_user(username="root", role="admin"))
        resp = client.get(path, params={"page_size": 1000}, headers=headers)
        assert resp.status_code == 422

    @pytest.mark.parametrize("path", LIST_ENDPOINTS)
    def test_page_below_one_rejected(self, client, make_user, auth_headers, path):
        """page=0 会算出负的 OFFSET，直接 422 掉"""
        headers = auth_headers(make_user(username="root", role="admin"))
        resp = client.get(path, params={"page": 0}, headers=headers)
        assert resp.status_code == 422

    @pytest.mark.parametrize("path", LIST_ENDPOINTS)
    def test_boundary_values_accepted(self, client, make_user, auth_headers, path):
        """100 是前端分页器实际会用到的最大值（设备页一次拉全部实验室），别卡成排他"""
        headers = auth_headers(make_user(username="root", role="admin"))
        resp = client.get(path, params={"page": 1, "page_size": 100}, headers=headers)
        assert resp.status_code == 200


class TestLabListStatusFilter:
    """A6b：status=0（已关闭）以前会被 `if status` 当成"没传"，反而返回全部"""

    def test_status_zero_filters_closed_labs(
        self, client, make_user, make_lab, auth_headers
    ):
        make_lab(name="开着的", status=1)
        make_lab(name="关着的", status=0)

        resp = client.get(
            "/api/lab/list", params={"status": 0}, headers=auth_headers(make_user())
        )
        body = resp.json()["data"]
        assert body["total"] == 1
        assert [item["name"] for item in body["list"]] == ["关着的"]

    def test_status_omitted_still_returns_everything(
        self, client, make_user, make_lab, auth_headers
    ):
        make_lab(name="开着的", status=1)
        make_lab(name="关着的", status=0)

        resp = client.get("/api/lab/list", headers=auth_headers(make_user()))
        assert resp.json()["data"]["total"] == 2


class TestStringFieldLengthCaps:
    """A8：上限跟着列宽走，超长在入口变成 422，而不是 MySQL 的 DataError -> 500"""

    def test_register_username_capped(self):
        with pytest.raises(ValidationError):
            RegisterRequest(username="u" * 51, password="pw123456")

    def test_user_email_capped(self):
        with pytest.raises(ValidationError):
            UserUpdateRequest(email="a" * 51)

    def test_lab_fields_capped(self):
        with pytest.raises(ValidationError):
            LabCreateRequest(name="名" * 51)
        with pytest.raises(ValidationError):
            LabCreateRequest(name="正常", description="字" * 501)
        with pytest.raises(ValidationError):
            LabCreateRequest(name="正常", location="位" * 101)

    def test_reservation_remark_capped(self):
        with pytest.raises(ValidationError):
            ReservationCreateRequest(
                lab_id=1,
                date="2026-10-09",
                start_time="09:00",
                end_time="10:00",
                remark="字" * 256,
            )

    def test_boundary_lengths_accepted(self):
        LabCreateRequest(name="名" * 50, description="字" * 500, location="位" * 100)

    def test_overlong_field_is_422_not_500(self, client, make_user, auth_headers):
        """以前这条会一路走到 MySQL，严格模式下抛 DataError 变成 500"""
        headers = auth_headers(make_user(username="root", role="admin"))
        resp = client.post("/api/lab", json={"name": "名" * 51}, headers=headers)
        assert resp.status_code == 422


class TestEquipmentConflictScope:
    """A2r：设备冲突的范围只由 equipment_id 决定，不再叠一层 lab_id。

    设备是能被改挂到别的实验室的（equipment_service.update_equipment 直接按
    payload 里的 lab_id 改），老预约记的还是旧 lab_id。冲突查询要是再按
    lab_id 过滤，就看不见那条老预约了，同一台设备同一时段能被约两次。
    """

    def test_conflict_detected_after_equipment_moved_lab(
        self, db, make_user, make_lab, make_equipment, booking
    ):
        lab_a, lab_b = make_lab(name="A"), make_lab(name="B")
        eq = make_equipment(lab_id=lab_a.id)
        reservation_service.create_reservation(
            db, make_user(), booking(lab_a.id, equipment_id=eq.id)
        )

        eq.lab_id = lab_b.id  # 设备改挂到 B，已存在的预约仍记着 lab_a
        db.commit()

        with pytest.raises(BusinessException, match="实验室已被预约"):
            reservation_service.create_reservation(
                db, make_user(), booking(lab_b.id, equipment_id=eq.id)
            )
        assert db.query(Reservation).count() == 1

    def test_other_equipment_still_bookable(
        self, db, make_user, make_lab, make_equipment, booking
    ):
        """收窄范围别收过头：同一实验室里另一台设备照约不误"""
        lab = make_lab()
        first = make_equipment(lab_id=lab.id)
        second = make_equipment(lab_id=lab.id, name="示波器")

        reservation_service.create_reservation(
            db, make_user(), booking(lab.id, equipment_id=first.id)
        )
        reservation_service.create_reservation(
            db, make_user(), booking(lab.id, equipment_id=second.id)
        )
        assert db.query(Reservation).count() == 2
