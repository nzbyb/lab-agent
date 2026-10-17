"""AI 评测：拿一批固定问题去问 Agent，按关键词判对错，出一份 JSON 报告。

用法（都在 backend/ 目录下执行，虚拟环境已装好依赖）：

    python scripts/eval_agent.py                      跑全部题目
    python scripts/eval_agent.py --only open-saturday 只跑一题，调试用
    python scripts/eval_agent.py --list               只列出题目，不跑

两三分钟能跑完，会真的调用大模型（花 token）。

为什么要钉死时钟
----------------
开放时间这类问题跟"现在几点"绑在一起。不钉死的话，"现在有哪些实验室开放"
的正确答案每天都不一样，这份评测就没法复现——今天周一跑是 8 间，明天周六跑
就只剩 2 间，你会以为是模型坏了。所以每道题自带一个 now，跑之前把项目里三处
读时钟的地方换掉：

    agent_service.datetime  → 提示词里那句"当前是 X 年 X 月 X 日 星期 X HH:MM"
    agent_tools.datetime    → get_today 工具返回的日期
    lab_service._now        → 今日开放时段、open_now 的判断

别的模块（预约落库的时间戳之类）不动：评测不建预约，用不到。

为什么只连本机数据库
--------------------
题目里的"8 间实验室""40 人""RTX4090 有 2 块"都是 demo_data.sql 的事实。
连到别的库（尤其是线上生产库）这些数字就全变了，评测结果没有意义，还会在
生产库上白跑一遍检索。所以脚本启动时先看 DATABASE_URL 的主机名，不是本机
就直接退出。确实要连远端库，加 --allow-remote-db，自己承担后果。

判分方式与局限
--------------
关键词判分便宜、快、不花钱再调一次模型，但它只认字面。"不能"和"不可以"要
都列进同义词组；模型答得再对，换个说法也可能被判错。所以：

  - 判错不等于模型答错，要人眼看那条回答；
  - 改完提示词先跑一遍，把新增的失败逐条确认，再决定是改题还是改提示词。

报告默认写到 scripts/eval_report.json（在 .gitignore 里），README 里只写
"日期 + 模型 + 通过数"这种结论。
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# 让 `python scripts/eval_agent.py` 能直接跑（不必先 pip install -e .）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.engine import make_url  # noqa: E402

from app.config import settings  # noqa: E402
from app.schemas.ai import ChatRequest  # noqa: E402
from app.services import agent_service, agent_tools, lab_service  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_QUESTIONS = Path(__file__).resolve().parent / "eval_questions.json"
DEFAULT_OUT = Path(__file__).resolve().parent / "eval_report.json"

# 当前这道题要钉的时刻。FrozenDateTime.now() 每次读它，所以换题只要改这个变量。
_frozen_now = datetime(2026, 10, 19, 10, 0, 0)


class FrozenDateTime(datetime):
    """datetime 的子类，now() 永远返回 _frozen_now。"""

    @classmethod
    def now(cls, tz=None):  # noqa: D401 - 和标准库签名保持一致
        return _frozen_now

    @classmethod
    def utcnow(cls):
        return _frozen_now


def install_frozen_clock() -> None:
    agent_service.datetime = FrozenDateTime
    agent_tools.datetime = FrozenDateTime
    lab_service._now = lambda: _frozen_now


def normalize(text: str) -> str:
    """去掉全部空白并转小写。中文回答里空格位置很随意，"8 间"和"8间"要一视同仁。"""
    return "".join(text.lower().split())


def judge(answer: str, item: dict) -> list[str]:
    """返回没通过的原因列表；空列表 = 通过。"""
    text = normalize(answer)
    failures = []

    for group in item.get("must_contain_any") or []:
        if not any(normalize(word) in text for word in group):
            failures.append("缺少任一：" + " / ".join(group))

    for word in item.get("must_not_contain") or []:
        if normalize(word) in text:
            failures.append("不该出现：" + word)

    return failures


async def ask(user_id: int, question: str) -> dict:
    """跑一轮 Agent，收集回答正文、用过的工具、报错。"""
    request = ChatRequest(
        messages=[{"role": "user", "content": question}],
        # 不落库：评测跑 20 遍，不该往聊天历史里塞 20 条
        session_key=None,
    )
    tokens: list[str] = []
    tools: list[str] = []
    errors: list[str] = []

    async for event in agent_service.stream_agent(user_id, request):
        kind = event.get("type")
        if kind == "token":
            tokens.append(event.get("content") or "")
        elif kind == "tool_start":
            name = event.get("name") or ""
            if name not in tools:
                tools.append(name)
        elif kind == "error":
            errors.append(event.get("message") or "")

    return {"answer": "".join(tokens), "tools": tools, "errors": errors}


async def main() -> int:
    global _frozen_now

    parser = argparse.ArgumentParser(description="跑 AI 评测集")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--only", default="", help="只跑这些 id，逗号分隔")
    parser.add_argument("--user-id", type=int, default=1,
                        help="以哪个账号的身份提问，默认 1（admin）")
    parser.add_argument("--timeout", type=float, default=180,
                        help="单题超时秒数，默认 180")
    parser.add_argument("--list", action="store_true", help="只列出题目")
    parser.add_argument("--allow-remote-db", action="store_true",
                        help="允许连非本机数据库（想清楚再开）")
    args = parser.parse_args()

    payload = json.loads(args.questions.read_text(encoding="utf-8"))
    items = payload["questions"]

    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        items = [item for item in items if item.get("id") in wanted]
        missing = wanted - {item.get("id") for item in items}
        if missing:
            sys.exit("没有这些题：" + ", ".join(sorted(missing)))

    if args.list:
        for item in items:
            print(f"{item['id']:<28} {item['now']}  {item['question']}")
        return 0

    # 只信本机库。见文件开头"为什么只连本机数据库"。
    host = make_url(settings.DATABASE_URL).host or ""
    if host not in ("localhost", "127.0.0.1", "::1", "") and not args.allow_remote_db:
        sys.exit(
            f"DATABASE_URL 指向 {host}，不是本机。评测题目绑定的是 demo_data.sql 的"
            "数据，连别的库结果没意义，而且不该在生产库上跑。确实要跑就加 --allow-remote-db。"
        )

    install_frozen_clock()

    print(f"模型：{settings.LLM_MODEL}")
    print(f"题目：{args.questions}")
    print(f"共 {len(items)} 题，账号 user_id={args.user_id}")
    print()

    results = []
    started_at = datetime.now()
    for index, item in enumerate(items, start=1):
        _frozen_now = datetime.fromisoformat(item["now"])

        print(f"[{index}/{len(items)}] {item['id']}：{item['question']}")
        began = datetime.now()
        try:
            outcome = await asyncio.wait_for(
                ask(args.user_id, item["question"]), timeout=args.timeout
            )
        except asyncio.TimeoutError:
            outcome = {"answer": "", "tools": [], "errors": ["超时"]}
        except Exception as exc:  # noqa: BLE001 - 单题崩了不能带崩整轮
            outcome = {"answer": "", "tools": [], "errors": [repr(exc)]}
        elapsed = (datetime.now() - began).total_seconds()

        failures = judge(outcome["answer"], item)
        if outcome["errors"]:
            failures.append("Agent 报错：" + "；".join(outcome["errors"]))
        passed = not failures

        tools_text = "、".join(outcome["tools"]) or "无"
        print(f"  {'PASS' if passed else 'FAIL'}  {elapsed:.1f}s  工具：{tools_text}")
        if not passed:
            for reason in failures:
                print(f"    - {reason}")
            print(f"    回答：{outcome['answer'][:200]}")
        print()

        results.append({
            "id": item["id"],
            "question": item["question"],
            "now": item["now"],
            "note": item.get("note", ""),
            "passed": passed,
            "failures": failures,
            "answer": outcome["answer"],
            "tools": outcome["tools"],
            "seconds": round(elapsed, 1),
        })

    passed_count = sum(1 for r in results if r["passed"])
    report = {
        "generated_at": started_at.isoformat(timespec="seconds"),
        "model": settings.LLM_MODEL,
        "user_id": args.user_id,
        "total": len(results),
        "passed": passed_count,
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("=" * 60)
    print(f"通过 {passed_count}/{len(results)}（{passed_count / len(results):.0%}）")
    print(f"报告：{args.out}")
    if passed_count < len(results):
        print("没过的题：")
        for item in results:
            if not item["passed"]:
                print(f"  - {item['id']}：{'；'.join(item['failures'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
