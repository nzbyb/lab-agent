"""限流的三个「体验」改动。

一、429 要说清楚「等多久」——响应头带 Retry-After，body 里也把秒数写出来。
    没有它，用户只知道"太频繁了"，不知道等 3 秒还是等 1 分钟，最容易的做法
    就是立刻再点，然后继续吃 429。

二、登录按「IP + 账号」计数。
    原来只有一条「每 IP 5 次/分钟」，校园网几十个人共用一个出口 IP，
    一个人连错几次，别人就一起被锁——这正是要修的"被误伤"。

三、AI 有并发上限，满了直接回一句"稍后再试"，不排队。
    每次对话要占住一条流式连接、在本机跑一次向量检索，2C4G 的机器开太多
    会互相拖慢。这条同时钉住"名额一定还得回来"——漏还一次就永久少一个坑。
"""

import asyncio
import json

import pytest

from app.api import ai
from app.config import settings
from app.schemas.ai import ChatMessage, ChatRequest
from app.services import agent_service, chat_service

LOGIN = "/api/auth/login"


@pytest.fixture(autouse=True)
def _reset_ai_slots():
    """AI 名额计数器是模块级状态，跟着用例重置。

    不重置的话，某条用例里泄漏一个名额，后面的用例会看到"上限 3 却只剩 2"，
    而且错得很隐蔽——只在整套跑的时候红。
    """
    ai._ai_inflight = 0
    yield
    ai._ai_inflight = 0


class TestRetryAfter:
    def test_429_carries_retry_after_and_says_seconds(self, client, make_user):
        make_user(username="alice", password="pw123456")

        # 前 5 次在额度内，第 6 次才拦。密码故意输错，避免真的登录成功。
        for _ in range(5):
            resp = client.post(
                LOGIN, json={"username": "alice", "password": "wrong"}
            )
            assert resp.status_code == 200

        resp = client.post(LOGIN, json={"username": "alice", "password": "wrong"})
        assert resp.status_code == 429

        header = resp.headers.get("Retry-After")
        assert header is not None, "429 必须带 Retry-After，否则前端不知道该等多久"
        assert header.isdigit() and int(header) >= 1, f"Retry-After 不合法：{header!r}"

        body = resp.json()
        assert body["code"] == 429
        assert str(header) in body["message"], "body 里的提示也应当写出秒数"
        assert "秒" in body["message"]

    def test_account_name_is_normalized(self, client, make_user):
        """换大小写、加首尾空格不能算成一个新账号。

        不归一化的话，`ALICE`、`alice ` 各占一个桶，这条限制换个写法就绕过去了。
        """
        make_user(username="alice", password="pw123456")

        for _ in range(5):
            client.post(LOGIN, json={"username": "alice", "password": "wrong"})

        resp = client.post(LOGIN, json={"username": "  ALICE  ", "password": "wrong"})
        assert resp.status_code == 429


class TestLoginPerAccount:
    def test_other_account_on_same_ip_is_not_affected(self, client, make_user):
        """同一出口 IP 下，alice 把额度用完不该连累 bob。

        这就是"被误伤"那条：多人共用一个 IP 时，别人试错密码不该把你也锁住。
        """
        make_user(username="alice", password="pw123456")
        make_user(username="bob", password="pw123456")

        for _ in range(5):
            client.post(LOGIN, json={"username": "alice", "password": "wrong"})
        blocked = client.post(LOGIN, json={"username": "alice", "password": "wrong"})
        assert blocked.status_code == 429

        # bob 用正确密码登录：既不该 429，也该成功。
        # 注意这里的判据是 body.code：本项目业务错误一律包在 HTTP 200 里。
        resp = client.post(LOGIN, json={"username": "bob", "password": "pw123456"})
        assert resp.status_code == 200, "别的账号不该被 alice 的失败次数牵连"
        assert resp.json()["code"] == 200
        assert resp.json()["data"]["token"]


class TestAIConcurrency:
    """同时进行的 AI 对话不超过 AI_MAX_CONCURRENCY。"""

    def test_second_request_is_rejected_and_slot_returns(
        self, monkeypatch, db, make_user
    ):
        monkeypatch.setattr(settings, "AI_MAX_CONCURRENCY", 1)

        user = make_user(username="alice")

        started = asyncio.Event()
        release = asyncio.Event()

        async def _blocking_stream(user_id, data):
            started.set()
            await release.wait()
            yield {"type": "token", "content": "你好"}
            yield {"type": "done"}

        # 落库不是这条用例要测的：换成记账的假实现，免得依赖真实对话表。
        saved = []
        monkeypatch.setattr(chat_service, "record_user_turn", lambda *a, **kw: 1)
        monkeypatch.setattr(
            chat_service,
            "record_assistant_turn",
            lambda *a, **kw: saved.append((a, kw)),
        )
        monkeypatch.setattr(agent_service, "stream_agent", _blocking_stream)

        body = ChatRequest(messages=[ChatMessage(role="user", content="你好")])

        async def _run():
            first = ai._event_stream(user.id, body)
            # 拉到第一个事件才会真正开始跑，即此时名额已经拿到
            first_task = asyncio.create_task(first.__anext__())
            await asyncio.wait_for(started.wait(), timeout=5)
            assert ai._ai_inflight == 1

            # 第二条：名额已满，应当直接回一条 error 事件，不碰 agent
            second_events = [ev async for ev in ai._event_stream(user.id, body)]
            assert ai._ai_inflight == 1, "被拒的那条不该改动名额"

            # 放行第一条，让它自然跑完
            release.set()
            first_event = await asyncio.wait_for(first_task, timeout=5)
            rest = [ev async for ev in first]
            return first_event, rest, second_events

        first_event, rest, second_events = asyncio.run(_run())

        assert len(second_events) == 1
        # 必须是一条 SSE 文本，不能直接 yield 一个 dict：StreamingResponse 只收
        # bytes/str，dict 会在响应头已经发出去之后才炸，客户端看到的是断流。
        assert isinstance(second_events[0], str)
        assert second_events[0].startswith("data: ")
        rejected = json.loads(second_events[0][len("data: "):].strip())
        assert rejected["type"] == "error"
        assert "过一会儿再试" in rejected["message"]

        # 第一条正常吐完了内容，说明被拒的只有第二条
        assert "你好" in first_event
        assert any("done" in ev for ev in rest)

        assert ai._ai_inflight == 0, "跑完必须把名额还回去，否则几次之后 AI 就永久'忙'"

        # 被拒的那条不该落库；第一条正常落库一次
        assert len(saved) == 1
        assert saved[0][0][2] == "你好"  # (user_id, session_key, text, steps)

    def test_rejection_is_valid_sse_over_http(
        self, monkeypatch, client, make_user, auth_headers
    ):
        """走完整的 HTTP 链路再确认一遍。

        上面那条直接驱动生成器，绕过了 StreamingResponse——而"把 dict 当文本
        yield 出去"恰恰只有经过 StreamingResponse 才会暴露：响应头已经发出，
        中途抛错，用户看到的是断流而不是提示。把上限设成 0，第一条就该被拒。
        """
        monkeypatch.setattr(settings, "AI_MAX_CONCURRENCY", 0)
        user = make_user(username="alice")

        resp = client.post(
            "/api/ai/chat/stream",
            headers=auth_headers(user),
            json={"messages": [{"role": "user", "content": "你好"}]},
        )

        assert resp.status_code == 200
        assert resp.text.startswith("data: ")
        payload = json.loads(resp.text[len("data: "):].strip())
        assert payload["type"] == "error"
        assert "过一会儿再试" in payload["message"]
        assert ai._ai_inflight == 0

    def test_slot_is_released_when_client_disconnects(self, monkeypatch, db, make_user):
        """用户中途关网页（生成器被取消）时，名额同样要还回来。

        这是最容易漏的一条：取消走的是 CancelledError，不是 Exception，
        清理代码只写在 except 里的话，这里会红。
        """
        monkeypatch.setattr(settings, "AI_MAX_CONCURRENCY", 1)

        user = make_user(username="alice")

        started = asyncio.Event()
        release = asyncio.Event()

        async def _hanging_stream(user_id, data):
            started.set()
            await release.wait()
            yield {"type": "token", "content": "半句话"}
            yield {"type": "done"}

        monkeypatch.setattr(chat_service, "record_user_turn", lambda *a, **kw: 1)
        monkeypatch.setattr(
            chat_service, "record_assistant_turn", lambda *a, **kw: None
        )
        monkeypatch.setattr(agent_service, "stream_agent", _hanging_stream)

        body = ChatRequest(messages=[ChatMessage(role="user", content="你好")])

        async def _run():
            stream = ai._event_stream(user.id, body)
            task = asyncio.create_task(stream.__anext__())
            await asyncio.wait_for(started.wait(), timeout=5)
            assert ai._ai_inflight == 1

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(_run())
        assert ai._ai_inflight == 0, "断线后名额没还，几次之后 AI 就永久'忙'了"
