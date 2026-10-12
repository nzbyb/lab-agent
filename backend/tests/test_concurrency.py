"""两处「同时跑」的坑。

**一、并发预约。**
create_reservation 的流程是「先查有没有冲突 → 没有就插入」，
中间没有加锁，表上也没有能兜底的唯一约束。
这意味着两个请求可能同时通过冲突检查，然后双双插入成功。
TestConcurrentBooking 就是来验证这条窗口是否真实存在的。

**二、AI 的多个工具同时查库。**
模型在一条回复里可以一口气发出多个工具调用，langgraph 的 ToolNode
用 asyncio.gather 并发跑它们，同步工具被丢进**各自的线程**。
这些工具曾经共用一个 SQLAlchemy Session——SQLAlchemy 明令禁止一个
Session 被并发使用，8 个并发里 1 个成功、7 个失败，用户看到的是
「大模型调用失败」。TestAgentToolConcurrency 钉住的就是这件事。
"""

import json
import threading
import types

import pytest

from app.common.exceptions import BusinessException
from app.database import SessionLocal
from app.models.reservation import Reservation
from app.services import reservation_service

WORKERS = 8
ROUNDS = 20


def _parallel_book(user_id, request_body, barrier, results, index):
    """一个线程抢一次预约。barrier 让 8 个线程尽量在同一瞬间进入。"""
    session = SessionLocal()
    try:
        barrier.wait(timeout=15)
        # 服务里只用到 current_user.id，给个轻量对象即可，免得跨会话传递 ORM 实例
        reservation_service.create_reservation(
            session, types.SimpleNamespace(id=user_id), request_body
        )
        results.append(("success", index))
    except BusinessException as exc:
        results.append(("rejected", exc.message))
    except Exception as exc:  # noqa: BLE001
        results.append(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        session.close()


pytestmark = pytest.mark.concurrency


class TestConcurrentBooking:
    def test_single_round_only_one_winner(
        self, db, make_user, make_lab, booking
    ):
        """8 路并发抢同一时段，期望恰好 1 个成功、7 个被拒"""
        user, lab = make_user(), make_lab()
        request_body = booking(lab.id, start_time="09:00", end_time="10:00")

        barrier = threading.Barrier(WORKERS)
        results = []
        threads = [
            threading.Thread(
                target=_parallel_book,
                args=(user.id, request_body, barrier, results, i),
            )
            for i in range(WORKERS)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        successes = [r for r in results if r[0] == "success"]
        errors = [r for r in results if r[0] == "error"]

        # 必须结束当前事务再查：MySQL 默认 REPEATABLE READ，
        # 不 rollback 的话这里读到的还是起跑前那份快照，永远看不见线程刚提交的行。
        db.rollback()
        rows = db.query(Reservation).count()

        print(f"\n  成功 {len(successes)} / 被拒 {len(results) - len(successes) - len(errors)}"
              f" / 异常 {len(errors)}  ->  库里实际 {rows} 条")
        for e in errors:
            print("   异常:", e[1])

        assert not errors, f"出现非预期异常: {errors}"
        assert rows == 1, f"重复预约！8 路并发后库里出现了 {rows} 条同一时段的预约"
        assert len(successes) == 1

    def test_many_rounds_never_double_book(
        self, db, make_user, make_lab, booking
    ):
        """反复跑 20 轮。轮数越多，撞上竞态窗口的概率越大。"""
        user, lab = make_user(), make_lab()
        worst = 0
        bad_rounds = []

        for round_no in range(ROUNDS):
            request_body = booking(lab.id, start_time="09:00", end_time="10:00")
            barrier = threading.Barrier(WORKERS)
            results = []
            threads = [
                threading.Thread(
                    target=_parallel_book,
                    args=(user.id, request_body, barrier, results, i),
                )
                for i in range(WORKERS)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            db.rollback()  # 同上：结束旧事务，否则读到的是陈旧快照
            rows = db.query(Reservation).count()
            if rows > worst:
                worst = rows
            if rows != 1:
                bad_rounds.append((round_no, rows))

            db.query(Reservation).delete()
            db.commit()

        assert not bad_rounds, (
            f"{ROUNDS} 轮中有 {len(bad_rounds)} 轮出现重复预约，"
            f"最严重时同一时段有 {worst} 条：{bad_rounds[:5]}"
        )


def _invoke_tool(tool, args, barrier, results, index):
    """一个线程调一次工具——ToolNode 对同步工具做的事就是这个。

    注意这个函数**不能只靠异常来判断成功**：工具内部把异常吞成了
    `{"ok": false, "error": "操作失败，请稍后重试"}`，返回值照常是个字符串。
    断言必须去看那个返回值里有没有真东西。
    """
    try:
        barrier.wait(timeout=15)
        results.append(("ok", index, tool.invoke(args)))
    except Exception as exc:  # noqa: BLE001
        results.append(("error", index, f"{type(exc).__name__}: {exc}"))


class TestAgentToolConcurrency:
    """AI 的多个工具调用必须能同时查库。

    8 个线程同时 invoke 同一个工具对象，恰好复刻 ToolNode 的做法。
    每个工具各开各的会话时这里 8/8 成功；退回「所有工具共用一个传入的会话」
    的老写法，这里会红——那不是理论风险，是真实发生过的故障。
    """

    def test_parallel_free_slots_all_succeed(self, db, make_user, make_lab, booking):
        from app.services import agent_tools

        user, lab = make_user(), make_lab()
        body = booking(lab.id, start_time="09:00", end_time="10:00")
        reservation_service.create_reservation(db, user, body)

        tools = {t.name: t for t in agent_tools.build_tools(user.id)}
        free_slots = tools["list_lab_free_slots"]
        args = {"lab_id": lab.id, "date": body.date}

        barrier = threading.Barrier(WORKERS)
        results = []
        threads = [
            threading.Thread(
                target=_invoke_tool,
                args=(free_slots, args, barrier, results, i),
            )
            for i in range(WORKERS)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        crashed = [r for r in results if r[0] == "error"]
        assert not crashed, f"并发调用工具时抛出了异常: {crashed}"
        assert len(results) == WORKERS, f"只回来了 {len(results)} 个结果"

        payloads = []
        for _, index, raw in sorted(results, key=lambda r: r[1]):
            payload = json.loads(raw)
            # 失败的返回值是 {"ok": false, "error": "操作失败，请稍后重试"}，
            # 不会带 lab_id。用这个当判据，比看异常靠谱。
            assert "lab_id" in payload, (
                f"8 路并发里第 {index} 个查询没查到空闲时段，工具返回：{payload}"
            )
            payloads.append(payload)

        # 查的是同一个实验室、同一天，8 份结果必须一模一样
        assert payloads[0] == payloads[-1]
        assert [item["start_time"] for item in payloads[0]["busy_slots"]] == ["09:00"]
        assert [item["start_time"] for item in payloads[0]["free_slots"]] == [
            "08:00",
            "10:00",
        ]
