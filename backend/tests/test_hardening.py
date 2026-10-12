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
    B3  已关闭实验室不列设备 -> TestClosedLabEquipmentVisibility
    B4  新建用户必须给密码  -> TestCreateUserPasswordRequired
    B5  出错信息不回显输入  -> TestErrorMessagesHideUserData
"""

import json
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.common.exceptions import BusinessException
from app.models.reservation import Reservation
from app.models.user import User
from app.schemas.ai import ChatMessage, ChatRequest
from app.schemas.auth import LoginRequest, RegisterRequest
from app.schemas.equipment import EquipmentCreateRequest, EquipmentUpdateRequest
from app.schemas.lab import LabCreateRequest, LabUpdateRequest
from app.schemas.reservation import (
    ReservationCreateRequest,
    normalize_date,
    normalize_time,
)
from app.schemas.user import UserCreateRequest, UserUpdateRequest
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
        tools = {t.name: t for t in agent_tools.build_tools(make_user().id)}
        result = json.loads(tools["search_lab_docs"].invoke("随便问点什么"))

        assert result["ok"] is False
        assert "hunter2" not in result["error"], "不能把绑定参数带出去"
        assert "SELECT" not in result["error"], "不能把 SQL 语句带出去"

    def test_agent_validation_error_gives_actionable_hint(self, db, make_user):
        """A1 加了格式校验后，模型传错格式要能拿到可自我纠正的提示。

        不能让它被通用兜底吞成一句笼统的失败——那样模型就失去了重试的线索。
        """
        from app.services import agent_tools

        tools = {t.name: t for t in agent_tools.build_tools(make_user().id)}
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
        async def fake_stream(user_id, data):
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

    # 下面几条是同一件事（上限跟着列宽走）在其它 schema 上的补齐。
    # 之前只有 lab 建库和 user 改名两处有用例，equipment / 建用户 / 登录 /
    # 注册 / 改实验室这几处的 Field(max_length=...) 都是「写是写了，没人守」。

    def test_user_create_fields_capped(self):
        with pytest.raises(ValidationError):
            UserCreateRequest(username="u" * 51, password="pw123456")
        for field in ("name", "email", "phone", "avatar"):
            with pytest.raises(ValidationError, match=field):
                UserCreateRequest(
                    username="normal", password="pw123456", **{field: "字" * 51}
                )
        with pytest.raises(ValidationError, match="role"):
            UserCreateRequest(username="normal", password="pw123456", role="r" * 51)

    def test_equipment_fields_capped(self):
        with pytest.raises(ValidationError, match="name"):
            EquipmentCreateRequest(lab_id=1, name="设" * 51)
        with pytest.raises(ValidationError, match="description"):
            EquipmentCreateRequest(lab_id=1, name="normal", description="字" * 501)
        with pytest.raises(ValidationError, match="img"):
            EquipmentCreateRequest(lab_id=1, name="normal", img="i" * 201)
        with pytest.raises(ValidationError, match="spec"):
            EquipmentCreateRequest(lab_id=1, name="normal", spec="s" * 101)

    def test_equipment_update_fields_capped(self):
        """更新接口的字段全是可选的，得一个一个单独传才触发得到校验"""
        with pytest.raises(ValidationError, match="name"):
            EquipmentUpdateRequest(name="设" * 51)
        with pytest.raises(ValidationError, match="description"):
            EquipmentUpdateRequest(description="字" * 501)
        with pytest.raises(ValidationError, match="img"):
            EquipmentUpdateRequest(img="i" * 201)
        with pytest.raises(ValidationError, match="spec"):
            EquipmentUpdateRequest(spec="s" * 101)

    def test_equipment_boundary_lengths_accepted(self):
        """卡在上限上的长度必须能过——上限写小一位也是 bug"""
        EquipmentCreateRequest(
            lab_id=1,
            name="设" * 50,
            description="字" * 500,
            img="i" * 200,
            spec="s" * 100,
        )
        EquipmentUpdateRequest(
            name="设" * 50,
            description="字" * 500,
            img="i" * 200,
            spec="s" * 100,
        )

    def test_login_and_register_fields_capped(self):
        with pytest.raises(ValidationError, match="username"):
            LoginRequest(username="u" * 51, password="pw123456")
        with pytest.raises(ValidationError, match="username"):
            RegisterRequest(username="u" * 51, password="pw123456")
        with pytest.raises(ValidationError, match="name"):
            RegisterRequest(username="normal", password="pw123456", name="名" * 51)

    def test_lab_update_fields_capped(self):
        with pytest.raises(ValidationError, match="name"):
            LabUpdateRequest(name="名" * 51)
        with pytest.raises(ValidationError, match="description"):
            LabUpdateRequest(description="字" * 501)
        with pytest.raises(ValidationError, match="img"):
            LabUpdateRequest(img="i" * 101)
        with pytest.raises(ValidationError, match="location"):
            LabUpdateRequest(location="位" * 101)
        with pytest.raises(ValidationError, match="open_time"):
            LabUpdateRequest(open_time="0" * 21)
        with pytest.raises(ValidationError, match="close_time"):
            LabUpdateRequest(close_time="0" * 21)

    def test_lab_update_boundary_lengths_accepted(self):
        LabUpdateRequest(
            name="名" * 50,
            description="字" * 500,
            img="i" * 100,
            location="位" * 100,
            open_time="0" * 20,
            close_time="0" * 20,
        )


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


class TestClosedLabEquipmentVisibility:
    """B3：agent 的 list_lab_equipments 以前不判实验室状态。

    同批的 list_labs 和 list_lab_free_slots 都会挡住已停用的实验室
    （list_labs 列出它但 enabled=false，list_lab_free_slots 走 get_free_slots
    会抛「实验室未开放预约」），只有它把 lab_id 直接透传给
    equipment_service.get_equipment_page_list（那个函数只按 lab_id/keywords 过滤）。
    结果是模型能列出已关闭实验室的设备、带用户走完确认流程，最后才在
    create_lab_reservation 拿到「实验室未开放预约」——和前端入口一样，
    变成「填完才被拒」。

    这道判断只能待在工具层：get_equipment_page_list 同时被 HTTP 接口用着，
    而前端设备页**需要**能查看已关闭实验室的设备清单（只读，预约按钮由前端禁用）。
    """

    def test_closed_lab_returns_no_equipment(
        self, db, make_user, make_lab, make_equipment
    ):
        from app.services import agent_tools

        lab = make_lab(status=0)
        make_equipment(lab_id=lab.id)
        tools = {t.name: t for t in agent_tools.build_tools(make_user().id)}

        result = json.loads(tools["list_lab_equipments"].invoke({"lab_id": lab.id}))

        assert result["ok"] is False
        assert result["error"] == "实验室未开放预约"

    def test_open_lab_still_lists_equipment(
        self, db, make_user, make_lab, make_equipment
    ):
        """别拦过头：开放中的实验室照常列设备"""
        from app.services import agent_tools

        lab = make_lab(status=1)
        eq = make_equipment(lab_id=lab.id)
        tools = {t.name: t for t in agent_tools.build_tools(make_user().id)}

        result = json.loads(tools["list_lab_equipments"].invoke({"lab_id": lab.id}))

        assert result["total"] == 1
        assert result["equipments"][0]["id"] == eq.id

    def test_missing_lab_still_says_not_found(self, db, make_user):
        """新加的校验不能把 lab_service.get_lab 的「实验室不存在」吞成笼统失败"""
        from app.services import agent_tools

        tools = {t.name: t for t in agent_tools.build_tools(make_user().id)}
        result = json.loads(tools["list_lab_equipments"].invoke({"lab_id": 999999}))

        assert result["ok"] is False
        assert result["error"] == "实验室不存在"

    def test_http_equipment_list_still_allows_closed_lab(
        self, client, make_user, make_lab, make_equipment, auth_headers
    ):
        """守住边界：守卫只在 agent 工具层，HTTP 接口必须还能查已关闭实验室的设备。

        前端设备页就是靠这个接口渲染的。哪天有人图省事把判断塞进
        get_equipment_page_list，已关闭实验室的设备页会直接空掉——这条会先红。
        """
        lab = make_lab(status=0)
        make_equipment(lab_id=lab.id)

        resp = client.get(
            "/api/equipment/list",
            params={"lab_id": lab.id},
            headers=auth_headers(make_user()),
        )
        assert resp.json()["data"]["total"] == 1


class TestCreateUserPasswordRequired:
    """B4：POST /api/user 以前不传密码也能建号，建出来的账号拿 "123" 就能登录。

    这是管理员给别人开账号的入口，等于把默认口令写死进了代码。ce94ada 把
    password 从 `str = "123"` 改成必填。但只写「必填」还挡不住空串——
    UserCreateRequest(password="") 照样通过必填校验，还是能开出一个空密码的
    可登录账号，所以补了一道 min_length=3 的下界，跟前端新建用户表单
    （3-10 位）的规则对齐。

    前面几条是 schema 层的边界，最后一条才是真正算数的：打真接口，并且确认库里
    没多出账号。校验层拦住了、但 service 层又建了个人的情况，只有这条能发现。
    """

    def test_missing_password_rejected(self):
        with pytest.raises(ValidationError):
            UserCreateRequest(username="normal")

    def test_empty_password_rejected(self):
        """「必填」挡不住空串：password="" 依然能过必填校验"""
        with pytest.raises(ValidationError):
            UserCreateRequest(username="normal", password="")

    def test_too_short_password_rejected(self):
        with pytest.raises(ValidationError):
            UserCreateRequest(username="normal", password="ab")

    def test_minimum_password_accepted(self):
        assert UserCreateRequest(username="normal", password="abc").password == "abc"

    def test_api_rejects_user_without_password(
        self, client, db, make_user, auth_headers
    ):
        """不传密码的建号请求必须是 422，而且库里不能多出账号。

        「是 422」这个断言在这里是有信息量的：BusinessException 会被全局处理器
        包成 HTTP 200 + body.code，真正保留 422 的只有参数校验这一条路径。
        """
        admin = make_user(username="root", role="admin")
        before = db.query(User).count()

        resp = client.post(
            "/api/user", json={"username": "newbie"}, headers=auth_headers(admin)
        )

        assert resp.status_code == 422
        assert db.query(User).count() == before


class TestErrorMessagesHideUserData:
    """B5：出错信息里不能带上用户提交的内容。

    两条会漏的路径各守一条用例。

    第一条是 SQLAlchemy 的默认行为：数据库异常的消息里会原样附上绑定参数
    （`[parameters: (...)]`）。这个异常一旦冒到日志或者响应里，等于把用户数据
    一起泄出去。database.py 用 create_engine(..., hide_parameters=True) 关掉它。

    这里刻意不断言「配置项等于 True」——那种写法只能证明我们写了这一行，证明不了
    它真的生效，把那行删掉用例照样绿。所以改成主动造一个带哨兵值的 SQL 错误，
    再去读异常原文。
    """

    SENTINEL = "CANARY-9f3a2b-MUST-NOT-LEAK"

    def test_db_error_does_not_leak_bound_parameters(self, db):
        with pytest.raises(SQLAlchemyError) as excinfo:
            db.execute(
                text("SELECT * FROM table_that_does_not_exist WHERE x = :p"),
                {"p": self.SENTINEL},
            )
        message = str(excinfo.value)

        # 先确认抓到的确实是这条 SQL 的异常，否则下面两条可能是在验一个空字符串
        assert "table_that_does_not_exist" in message
        # 关键：绑定参数没有跟着异常一起泄漏
        assert self.SENTINEL not in message
        # 正向对照：参数是被主动屏蔽的，不是恰好没打印。
        # 少了这条，哪天 hide_parameters 被去掉，这个用例可能照样绿。
        # 实测两种取值下的异常原文（Connection 和 Session 两条路径结果一致）：
        #   开 -> [SQL parameters hidden due to hide_parameters=True]
        #   关 -> [parameters: {'p': 'CANARY-9f3a2b-MUST-NOT-LEAK'}]  <- 哨兵值就在这
        assert "hide_parameters" in message

    def test_validation_error_does_not_echo_input(
        self, client, make_user, auth_headers
    ):
        """参数校验失败的响应是固定文案，不回显提交上来的内容。

        回显看着无害，实际是把用户输入原样反射回去（超长的、带控制字符的、
        带 HTML 的都可能）。validation_exception_hadler 里那句写死的
        「请求参数校验错误」就是防这个的。

        哨兵值故意放在**触发校验失败的那个字段**上：只有它才会出现在
        pydantic 的错误详情里，一旦有人把处理器改成返回 exc.errors()，这条先红。
        """
        headers = auth_headers(make_user(username="root", role="admin"))
        canary = "echo-canary-" + "x" * 60  # 72 字符，必然超上限

        resp = client.post("/api/lab", json={"name": canary}, headers=headers)

        assert resp.status_code == 422
        assert canary not in resp.text
