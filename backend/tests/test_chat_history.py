"""AI 会话历史。

这一组里最重要的一条是 test_disconnect_mid_stream_still_saves_reply：
用户聊到一半关掉网页时，助手回复必须仍然落库。那是整个功能唯一会**静默丢数据**
的地方——丢了没有任何报错，只在断线时发生，事后极难查。

落库故意写在 api/ai.py 的路由层（不是 agent_service.stream_agent 里面），
所以这里的 fake 流只负责喂事件，落库逻辑照常执行、测得着。
"""

import asyncio
import contextlib
import json
from datetime import datetime, timedelta

from app.api.ai import _event_stream
from app.models.chat import ChatConversation, ChatMessage
from app.schemas.ai import ChatMessage as ChatMessageIn
from app.schemas.ai import ChatRequest
from app.services import agent_service, chat_service

CHAT_STREAM = "/api/ai/chat/stream"
CONVERSATIONS = "/api/chat/conversations"

CONV_ID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


def _fake_stream(*, text="你好", with_tool=True, tail_error=False):
    """造一个不真调模型的 SSE 事件流。返回 (生成器函数, 状态字典)。

    状态字典里的 finished 用来证明"这个流真的被中途掐断了"——只断言库里有行
    是不够的，得先证明我们确实没跑到最后。
    """
    state = {"finished": False}

    async def stream(user_id, data):
        yield {"type": "status", "message": "正在思考..."}
        if with_tool:
            yield {"type": "tool_start", "name": "get_today", "label": "获取今天的日期"}
            yield {
                "type": "tool_end",
                "name": "get_today",
                "label": "获取今天的日期",
                "preview": "{}",
            }
        if tail_error:
            yield {"type": "error", "message": "大模型调用失败，请稍后重试"}
        else:
            yield {"type": "token", "content": text}
        yield {"type": "done"}
        state["finished"] = True

    return stream, state


def _post_chat(client, headers, content="今天几号", session_key=CONV_ID):
    body = {"messages": [{"role": "user", "content": content}]}
    if session_key is not None:
        body["session_key"] = session_key
    return client.post(CHAT_STREAM, json=body, headers=headers)


def _sse_events(response) -> list[dict]:
    """把 SSE 响应体拆成事件列表。

    别的事件用例都只看数据库，但 done 事件里挂的那个 conversation_id 是
    **前后端之间唯一的跨层契约**，只存在于响应体里，不解析就测不到。
    """
    events = []
    for line in response.text.split("\n"):
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload:
            events.append(json.loads(payload))
    return events


def _visible(db):
    """结束测试自己这边的事务，否则看不到别的连接刚提交的行。

    落库用的是独立的 SessionLocal，而 MySQL 默认 REPEATABLE READ——
    不结束旧事务，这个会话的快照就永远停在过去。
    """
    db.rollback()


class TestStreamPersistence:
    def test_turn_is_persisted(self, client, db, make_user, auth_headers, monkeypatch):
        stream, _ = _fake_stream(text="今天是 10 月 11 日")
        monkeypatch.setattr(agent_service, "stream_agent", stream)

        user = make_user()
        assert _post_chat(client, auth_headers(user)).status_code == 200

        _visible(db)
        assert db.query(ChatConversation).count() == 1
        rows = db.query(ChatMessage).order_by(ChatMessage.id).all()
        assert [row.role for row in rows] == ["user", "assistant"]
        assert rows[0].content == "今天几号"
        assert rows[1].content == "今天是 10 月 11 日"
        # 工具调用过程也要存下来（需求里明确要的）
        steps = json.loads(rows[1].steps)
        assert steps[0]["name"] == "get_today"
        assert steps[0]["state"] == "done"

    def test_done_event_carries_conversation_id(
        self, client, db, make_user, auth_headers, monkeypatch
    ):
        """done 事件里必须带上会话的整型 id。

        这是前后端之间**唯一**的跨层契约：前端发上去的是字符串 session_key，
        而列表和消息接口认的是整型 id。把 ai.py 里那行
        `event = {**event, "conversation_id": conversation_id}` 删掉，
        其余用例照样全绿（它们断言的是库里的行和响应码），但前端再也拿不到 id——
        刷新恢复上次会话、切换会话、历史面板高亮会一起失效。
        别的事件用例都不解析响应体，所以这条不单独钉就没覆盖。
        """
        stream, _ = _fake_stream()
        monkeypatch.setattr(agent_service, "stream_agent", stream)

        user = make_user()
        res = _post_chat(client, auth_headers(user))
        assert res.status_code == 200

        done = [e for e in _sse_events(res) if e.get("type") == "done"]
        assert len(done) == 1, "一轮对话应当只有一个 done 事件"

        _visible(db)
        conv = db.query(ChatConversation).one()
        assert done[0].get("conversation_id") == conv.id

    def test_without_session_key_done_event_has_no_conversation_id(
        self, client, db, make_user, auth_headers, monkeypatch
    ):
        """不落库的那一轮，done 事件里不能凭空多出一个 conversation_id。

        老客户端不带 session_key，此时没有会话 id 可给。塞个 None 进去的话，
        前端 `evt.conversation_id && ...` 虽然挡得住，但契约就含糊了。
        """
        stream, _ = _fake_stream()
        monkeypatch.setattr(agent_service, "stream_agent", stream)

        user = make_user()
        res = _post_chat(client, auth_headers(user), session_key=None)

        done = [e for e in _sse_events(res) if e.get("type") == "done"]
        assert len(done) == 1
        assert "conversation_id" not in done[0]

    def test_disconnect_mid_stream_still_saves_reply(
        self, db, make_user, monkeypatch
    ):
        """聊到一半关掉网页：助手回复仍要落库。

        直接驱动生成器（不经过 HTTP），拿到几个事件后 aclose()——这就是浏览器
        断线时后端发生的事。注意走的**不是**正常收尾路径：流没跑完，
        finished 必须还是 False，而库里的行照样要在。
        """
        stream, state = _fake_stream(text="今天是 10 月 11 日")
        monkeypatch.setattr(agent_service, "stream_agent", stream)

        user = make_user()
        data = ChatRequest(
            messages=[ChatMessageIn(role="user", content="今天几号")],
            session_key=CONV_ID,
        )

        async def scenario():
            gen = _event_stream(user.id, data)
            seen = []
            async for event in gen:
                seen.append(event)
                # 收到几条就断——此时正文只吐了一部分
                if len(seen) >= 4:
                    break
            await gen.aclose()
            return seen

        asyncio.run(scenario())

        # 控制项：证明这个流确实是被掐断的，不是正常跑完
        assert state["finished"] is False, "这个用例必须真的中途断线才有意义"

        _visible(db)
        rows = db.query(ChatMessage).order_by(ChatMessage.id).all()
        assert [row.role for row in rows] == ["user", "assistant"]
        assert rows[1].content == "今天是 10 月 11 日"
        assert json.loads(rows[1].steps)[0]["state"] == "done"

    def test_disconnect_by_cancellation_still_saves_reply(
        self, db, make_user, monkeypatch
    ):
        """断线的另一种终结方式：取消（CancelledError），真实 uvicorn 走的就是这条。

        上一条测的是 aclose() 抛的 GeneratorExit，那更多是"生成器被回收"的路径。
        真的 HTTP 断线时，starlette 会把取消信号打进正在 await 的生成器内部——
        而 CancelledError **不属于 Exception**，agent_service 里那个兜底
        `except Exception` 拦不住它，循环之后的代码一律不执行。
        所以必须证明：这条路径同样只有 finally 兜得住。
        """
        state = {"blocked": False}

        async def stream(user_id, data):
            yield {"type": "token", "content": "说到一半"}
            state["blocked"] = True
            # 永远挂住，等被取消——模拟模型还在生成、连接突然断掉
            await asyncio.Event().wait()

        monkeypatch.setattr(agent_service, "stream_agent", stream)

        user = make_user()
        data = ChatRequest(
            messages=[ChatMessageIn(role="user", content="今天几号")],
            session_key=CONV_ID,
        )

        async def scenario():
            gen = _event_stream(user.id, data)

            async def consume():
                async for _ in gen:
                    pass

            task = asyncio.create_task(consume())
            for _ in range(200):
                await asyncio.sleep(0.01)
                if state["blocked"]:
                    break
            else:
                raise AssertionError("生成器没跑到挂起那一步，这个用例不成立")
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            # 控制项：证明这轮真的是被取消掉的。要是生成器自己跑完了，
            # 下面这条断言会挂——那说明这个用例根本没测到取消路径，是假的绿。
            assert task.cancelled(), "生成器没被取消，这个用例不成立"

        asyncio.run(scenario())

        _visible(db)
        rows = db.query(ChatMessage).order_by(ChatMessage.id).all()
        assert [row.role for row in rows] == ["user", "assistant"]
        assert rows[1].content == "说到一半"

    def test_error_event_is_not_saved_as_reply(
        self, client, db, make_user, auth_headers, monkeypatch
    ):
        """报错文案不能当成助手说过的话存进去。

        存了的话，下次回看、回灌给模型时，"大模型调用失败，请稍后重试"
        就变成了助手的发言。

        这一轮是"调了工具之后才报错"，所以助手那行**要留**（执行过程是真实发生过的），
        但正文必须是空的。
        """
        stream, _ = _fake_stream(tail_error=True)
        monkeypatch.setattr(agent_service, "stream_agent", stream)

        user = make_user()
        assert _post_chat(client, auth_headers(user)).status_code == 200

        _visible(db)
        rows = db.query(ChatMessage).order_by(ChatMessage.id).all()
        assert [row.role for row in rows] == ["user", "assistant"]
        assert rows[1].content == "", "报错文案绝不能落成助手说过的话"
        # 过程仍然留着——那轮确实调过工具
        assert json.loads(rows[1].steps)[0]["name"] == "get_today"

    def test_turn_with_neither_text_nor_steps_saves_no_reply(
        self, client, db, make_user, auth_headers, monkeypatch
    ):
        """什么产出都没有的一轮，不留空气泡。

        和上一条的区别：这里连工具都没调（模型第一条就挂了），
        正文和过程全空，助手那行不该存在。
        """
        stream, _ = _fake_stream(with_tool=False, tail_error=True)
        monkeypatch.setattr(agent_service, "stream_agent", stream)

        user = make_user()
        assert _post_chat(client, auth_headers(user)).status_code == 200

        _visible(db)
        rows = db.query(ChatMessage).order_by(ChatMessage.id).all()
        # 用户的提问要留下（那是真实发生过的），助手那条不存
        assert [row.role for row in rows] == ["user"]

    def test_without_session_key_nothing_is_persisted(
        self, client, db, make_user, auth_headers, monkeypatch
    ):
        """不带会话标识的请求照常能聊，只是不落库（老客户端兼容）。"""
        stream, _ = _fake_stream()
        monkeypatch.setattr(agent_service, "stream_agent", stream)

        user = make_user()
        assert _post_chat(client, auth_headers(user), session_key=None).status_code == 200

        _visible(db)
        assert db.query(ChatConversation).count() == 0
        assert db.query(ChatMessage).count() == 0

    def test_second_turn_lands_in_the_same_conversation(
        self, client, db, make_user, auth_headers, monkeypatch
    ):
        """同一个 session_key 的第二轮不能再建一条会话。"""
        stream, _ = _fake_stream()
        monkeypatch.setattr(agent_service, "stream_agent", stream)

        user = make_user()
        headers = auth_headers(user)
        _post_chat(client, headers, content="第一句")
        _post_chat(client, headers, content="第二句")

        _visible(db)
        assert db.query(ChatConversation).count() == 1
        rows = db.query(ChatMessage).order_by(ChatMessage.id).all()
        assert [row.role for row in rows] == ["user", "assistant", "user", "assistant"]

    def test_conversation_update_time_moves_forward(
        self, client, db, make_user, auth_headers, monkeypatch
    ):
        """会话行的更新时间必须跟着动。

        数据库只在**这一行本身**被 UPDATE 时才自动记时间；只往里插消息的话它不动，
        历史列表按时间倒序时刚聊完的会话就冒不到最上面。
        """
        stream, _ = _fake_stream()
        monkeypatch.setattr(agent_service, "stream_agent", stream)

        user = make_user()
        headers = auth_headers(user)
        _post_chat(client, headers, content="第一句")

        _visible(db)
        conv = db.query(ChatConversation).one()
        db.query(ChatConversation).filter(ChatConversation.id == conv.id).update(
            {ChatConversation.update_time: datetime.now() - timedelta(days=1)}
        )
        db.commit()
        stale = db.query(ChatConversation).one().update_time

        _post_chat(client, headers, content="第二句")

        _visible(db)
        assert db.query(ChatConversation).one().update_time > stale


class TestConversationAccess:
    @staticmethod
    def _seed(db, user_id, session_key, title, when):
        db.add(
            ChatConversation(
                user_id=user_id,
                session_key=session_key,
                title=title,
                update_time=when,
            )
        )
        db.commit()

    def test_list_returns_only_own(self, client, db, make_user, auth_headers):
        alice = make_user("alice")
        bob = make_user("bob")
        now = datetime.now()
        self._seed(db, alice.id, "alice-key-0001", "甲的对话", now)
        self._seed(db, bob.id, "bob-key-000001", "乙的对话", now)

        res = client.get(CONVERSATIONS, headers=auth_headers(alice)).json()
        assert res["code"] == 200
        titles = [item["title"] for item in res["data"]["list"]]
        assert titles == ["甲的对话"]
        assert res["data"]["total"] == 1

    def test_manager_cannot_see_others(self, client, db, make_user, auth_headers):
        """管理员也看不到别人的会话——刻意偏离预约那边"管理员看全库"的惯例。"""
        admin = make_user("boss", role="admin")
        student = make_user("stu")
        self._seed(db, student.id, "stu-key-000001", "学生的私事", datetime.now())

        res = client.get(CONVERSATIONS, headers=auth_headers(admin)).json()
        assert res["data"]["total"] == 0

    def test_messages_of_others_return_null(self, client, db, make_user, auth_headers):
        """读别人的会话给 200 + 空，不区分"不存在"和"不是你的"。"""
        alice = make_user("alice")
        bob = make_user("bob")
        self._seed(db, bob.id, "bob-key-000001", "乙的对话", datetime.now())
        conv_id = db.query(ChatConversation).one().id

        res = client.get(
            f"{CONVERSATIONS}/{conv_id}/messages", headers=auth_headers(alice)
        ).json()
        assert res["code"] == 200
        assert res["data"] is None

    def test_messages_of_missing_conversation_return_null(
        self, client, db, make_user, auth_headers
    ):
        """会话已被保留上限删掉时，进页面恢复不能弹报错，只能安静地拿不到。"""
        user = make_user()
        res = client.get(
            f"{CONVERSATIONS}/999999/messages", headers=auth_headers(user)
        ).json()
        assert res["code"] == 200
        assert res["data"] is None

    def test_delete_removes_messages_too(self, client, db, make_user, auth_headers):
        user = make_user()
        self._seed(db, user.id, "user-key-00001", "要删的", datetime.now())
        conv = db.query(ChatConversation).one()
        db.add(ChatMessage(conversation_id=conv.id, role="user", content="你好"))
        db.commit()

        res = client.delete(
            f"{CONVERSATIONS}/{conv.id}", headers=auth_headers(user)
        ).json()
        assert res["code"] == 200

        _visible(db)
        assert db.query(ChatConversation).count() == 0
        # 项目里没有级联删除，消息必须被显式删掉；漏了就是一堆孤儿行
        assert db.query(ChatMessage).count() == 0

    def test_cannot_delete_others(self, client, db, make_user, auth_headers):
        alice = make_user("alice")
        bob = make_user("bob")
        self._seed(db, bob.id, "bob-key-000001", "乙的对话", datetime.now())
        conv_id = db.query(ChatConversation).one().id

        res = client.delete(
            f"{CONVERSATIONS}/{conv_id}", headers=auth_headers(alice)
        ).json()
        assert res["code"] == 403

        _visible(db)
        assert db.query(ChatConversation).count() == 1

    def test_anonymous_is_rejected(self, client):
        # 故意不用 client fixture 之外的东西：未登录时三个接口都得挡住
        assert client.get(CONVERSATIONS).status_code == 401
        assert client.get(f"{CONVERSATIONS}/1/messages").status_code == 401
        assert client.delete(f"{CONVERSATIONS}/1").status_code == 401


class TestWhichMessageGetsStored:
    """「哪一条算这一轮的新提问」——判据是位置，不是内容。

    这个判据在 chat_service.extract_new_user_message 的 docstring 里写得很细，
    但原来一条用例都没覆盖：所有请求体都只发一条消息、每轮文本还都不一样，
    于是"按位置"和"按内容"两种实现跑出来的结果完全相同，测不出区别。
    """

    def test_full_history_stores_only_the_last_question(
        self, client, db, make_user, auth_headers, monkeypatch
    ):
        """前端真实发的是"整段历史 + 末尾新提问"，只能存末尾那一条。

        末尾那句**故意和上一轮一字不差**，一次钉住两个错误实现：
        - 按内容和库里比：会把它误判成重发，静默漏存；
        - 在历史里找最后一条 user：会把上一轮的提问再存一遍。
        """
        stream, _ = _fake_stream(text="答复")
        monkeypatch.setattr(agent_service, "stream_agent", stream)

        user = make_user()
        headers = auth_headers(user)
        _post_chat(client, headers, content="今天几号")

        body = {
            "messages": [
                {"role": "user", "content": "今天几号"},
                {"role": "assistant", "content": "答复"},
                {"role": "user", "content": "今天几号"},
            ],
            "session_key": CONV_ID,
        }
        assert client.post(CHAT_STREAM, json=body, headers=headers).status_code == 200

        _visible(db)
        asked = (
            db.query(ChatMessage)
            .filter(ChatMessage.role == "user")
            .order_by(ChatMessage.id)
            .all()
        )
        assert [row.content for row in asked] == ["今天几号", "今天几号"]
        # 整段历史里那些旧消息不能被重复存进来：两轮各 2 行，正好 4 行
        assert db.query(ChatMessage).count() == 4

    def test_history_ending_with_assistant_stores_nothing(
        self, client, db, make_user, auth_headers, monkeypatch
    ):
        """末尾是 assistant 的请求体：没有新提问，什么都不该存。

        这条对应 docstring 里"不能用在历史里找最后一条 user"那句——
        真那么实现的话，会把上一轮的提问当成新提问又存一遍。
        """
        stream, _ = _fake_stream()
        monkeypatch.setattr(agent_service, "stream_agent", stream)

        user = make_user()
        body = {
            "messages": [
                {"role": "user", "content": "今天几号"},
                {"role": "assistant", "content": "10 月 11 日"},
            ],
            "session_key": CONV_ID,
        }
        assert (
            client.post(CHAT_STREAM, json=body, headers=auth_headers(user)).status_code
            == 200
        )

        _visible(db)
        assert db.query(ChatConversation).count() == 0
        assert db.query(ChatMessage).count() == 0


class TestReadBack:
    """把一条会话读回来接着聊——这是本功能的主路径，原来一条正向用例都没有。

    对 GET /conversations/{id}/messages 原先只有三处调用，全是负向的
    （别人的、不存在的、未登录）。get_messages 里的 user_id 过滤、按 id 排序、
    steps 解析因此全都没有正向覆盖：真要是它对**本人**也返回 null、或者顺序倒了，
    原来那批用例照样全绿，而用户看到的就是"点历史没反应"。
    """

    def test_own_conversation_reads_back_in_order(
        self, client, db, make_user, auth_headers, monkeypatch
    ):
        stream, _ = _fake_stream(text="今天是 10 月 11 日")
        monkeypatch.setattr(agent_service, "stream_agent", stream)

        user = make_user()
        headers = auth_headers(user)
        _post_chat(client, headers, content="今天几号")
        _post_chat(client, headers, content="那明天呢")

        _visible(db)
        conv_id = db.query(ChatConversation).one().id

        res = client.get(f"{CONVERSATIONS}/{conv_id}/messages", headers=headers).json()
        assert res["code"] == 200
        rows = res["data"]

        # 顺序必须是 提问→答复→提问→答复（按 id 升序）
        assert [r["role"] for r in rows] == ["user", "assistant", "user", "assistant"]
        assert [r["content"] for r in rows] == [
            "今天几号",
            "今天是 10 月 11 日",
            "那明天呢",
            "今天是 10 月 11 日",
        ]
        # 工具过程要能读回来——回看时要显示"执行过程"
        assert rows[1]["steps"][0]["name"] == "get_today"
        assert rows[1]["steps"][0]["state"] == "done"
        # 用户消息没有过程
        assert rows[0]["steps"] is None
        # 时间要带上，气泡和历史列表都靠它显示
        assert rows[0]["create_time"]

    def test_broken_steps_json_does_not_break_readback(
        self, client, db, make_user, auth_headers
    ):
        """库里 steps 是坏 JSON 时回看要能正常返回，不能整条打挂。

        steps 是自由文本列，将来手改数据或迁移出问题都可能写进非法 JSON。
        解析失败只该当"这条没有过程"，不能让整次回看变成 500。
        """
        user = make_user()
        db.add(
            ChatConversation(user_id=user.id, session_key="bad-json-key-1", title="坏的")
        )
        db.commit()
        conv = db.query(ChatConversation).one()
        db.add(
            ChatMessage(
                conversation_id=conv.id,
                role="assistant",
                content="答复",
                steps="{这不是 JSON",
            )
        )
        db.commit()

        res = client.get(
            f"{CONVERSATIONS}/{conv.id}/messages", headers=auth_headers(user)
        ).json()
        assert res["code"] == 200
        assert res["data"][0]["content"] == "答复"
        assert res["data"][0]["steps"] is None


class TestRetentionLimit:
    def test_oldest_conversation_is_pruned(self, db, make_user):
        """每人最多 50 条，超出的连同消息一起删，且删的是最旧的。"""
        user = make_user()
        base = datetime.now() - timedelta(days=100)
        for i in range(chat_service._MAX_CONVERSATIONS):
            db.add(
                ChatConversation(
                    user_id=user.id,
                    session_key=f"old-key-{i:04d}",
                    title=f"会话 {i}",
                    # 显式给时间，让"最旧的"是确定的，不靠插入顺序
                    update_time=base + timedelta(minutes=i),
                )
            )
        db.commit()
        oldest = db.query(ChatConversation).order_by(ChatConversation.update_time).first()
        db.add(ChatMessage(conversation_id=oldest.id, role="user", content="老对话"))
        db.commit()
        oldest_id = oldest.id

        data = ChatRequest(
            messages=[ChatMessageIn(role="user", content="新的一轮")],
            session_key="brand-new-key",
        )
        assert chat_service.record_user_turn(user.id, data) is not None

        _visible(db)
        assert db.query(ChatConversation).count() == chat_service._MAX_CONVERSATIONS
        keys = {row[0] for row in db.query(ChatConversation.session_key).all()}
        assert "brand-new-key" in keys
        assert "old-key-0000" not in keys
        # 被删会话的消息不能剩下来
        assert db.query(ChatMessage).filter(
            ChatMessage.conversation_id == oldest_id
        ).count() == 0

    def test_under_limit_prunes_nothing(self, db, make_user):
        user = make_user()
        for i in range(3):
            db.add(
                ChatConversation(
                    user_id=user.id, session_key=f"keep-key-{i:03d}", title=f"会话 {i}"
                )
            )
        db.commit()

        data = ChatRequest(
            messages=[ChatMessageIn(role="user", content="再来一轮")],
            session_key="another-key-1",
        )
        chat_service.record_user_turn(user.id, data)

        _visible(db)
        assert db.query(ChatConversation).count() == 4


class TestRequestValidation:
    def test_session_key_too_long_is_422(self, client, make_user, auth_headers):
        """超长会话标识要在入口变成 422，而不是撞上列宽变成 500。"""
        headers = auth_headers(make_user())
        body = {
            "messages": [{"role": "user", "content": "你好"}],
            "session_key": "x" * 100,
        }
        assert client.post(CHAT_STREAM, json=body, headers=headers).status_code == 422

    def test_session_key_with_illegal_chars_is_422(self, client, make_user, auth_headers):
        headers = auth_headers(make_user())
        for bad in ("has space here", "有中文的标识符", "semi;colon;key"):
            body = {
                "messages": [{"role": "user", "content": "你好"}],
                "session_key": bad,
            }
            assert (
                client.post(CHAT_STREAM, json=body, headers=headers).status_code == 422
            ), f"{bad!r} 应当被拒"

    def test_error_message_does_not_leak_column_details(
        self, client, make_user, auth_headers
    ):
        """422 的响应体是一句通用文案，不回显请求内容。"""
        headers = auth_headers(make_user())
        body = {
            "messages": [{"role": "user", "content": "你好"}],
            "session_key": "x" * 100,
        }
        res = client.post(CHAT_STREAM, json=body, headers=headers)
        assert "session_key" not in res.text
        assert "x" * 50 not in res.text
