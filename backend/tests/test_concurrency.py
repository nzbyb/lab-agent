"""并发预约。

create_reservation 的流程是「先查有没有冲突 → 没有就插入」，
中间没有加锁，表上也没有能兜底的唯一约束。
这意味着两个请求可能同时通过冲突检查，然后双双插入成功。

这个文件就是来验证这条窗口是否真实存在的。
"""

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
