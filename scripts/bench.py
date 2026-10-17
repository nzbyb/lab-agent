#!/usr/bin/env python3
"""接口压测脚本。只用 Python 标准库，服务器上不用装任何东西。

为什么自己写而不上 wrk / locust：
- 这台服务器在国内，装工具要走 apt/pip，Docker Hub 又连不上，多一层麻烦；
- 我们要测的只有几个「登录后 GET 一下」的只读接口，不需要复杂的场景编排；
- 标准库版本一眼能看完，别人 clone 下来照着 README 就能复现数字。

它做的事：用一个账号登录一次拿到 token，然后按给定的并发数，对每个路径
持续发请求若干秒，统计吞吐和延迟分位。

**不要拿它打 AI 接口**：AI 慢在大模型那边，不是这台机器的能力；
而且有限流（20 次/分钟），测出来的只会是限流器。

用法（在服务器上，仓库根目录）：

    BENCH_USERNAME=demo BENCH_PASSWORD=你的密码 \
      python3 scripts/bench.py --base-url http://127.0.0.1:8080

常用参数：

    --path "/api/lab/list?page=1&page_size=10"   可以写多次，默认为三个只读接口
    --concurrency 1,10,50                        每个并发数各测一轮
    --duration 10                                每轮持续多少秒
    --token "eyJ..."                             已有令牌时跳过登录（反复跑时省事）

输出一张表，最后一列是错误率。所有请求都是新开 TCP 连接（不复用），
所以数字比带 keep-alive 的真实浏览场景更保守一些。

注意：登录接口本身有限流（同一 IP 同一账号 5 次/分钟）。正常跑一次只登录
一次，没问题；一分钟内连续跑五六次会被锁一分钟，用 --token 复用令牌就好。
"""

import argparse
import json
import os
import platform
import sys
import threading
import time
import urllib.error
import urllib.request

# Windows 控制台默认 cp936，直接 print 中文会乱码。这个脚本的输出全是给人看的，
# 编码错了等于什么都没打出来。Linux 服务器上这行是无害的空操作。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_PATHS = [
    "/api/lab/list?page=1&page_size=10",
    "/api/lab/1",
    "/api/equipment/list?page=1&page_size=10&lab_id=1",
]


def request_once(url, token, timeout):
    """发一次请求，返回 (状态码, 毫秒)。连不上时状态码记 0。"""
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", "Bearer " + token)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
            return resp.status, (time.perf_counter() - started) * 1000
    except urllib.error.HTTPError as exc:
        exc.read()
        return exc.code, (time.perf_counter() - started) * 1000
    except Exception:  # noqa: BLE001 - 超时、拒连都算一次失败
        return 0, (time.perf_counter() - started) * 1000


def login(base_url, username, password, timeout):
    url = base_url.rstrip("/") + "/api/auth/login"
    body = json.dumps({"username": username, "password": password}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"登录请求失败：{exc}")

    # 本项目的业务错误也放在 HTTP 200 里，所以必须看 body.code
    if payload.get("code") != 200:
        sys.exit(f"登录失败：{payload.get('message') or payload}")
    return payload["data"]["token"]


def percentile(sorted_values, p):
    if not sorted_values:
        return 0.0
    index = int(round((p / 100.0) * (len(sorted_values) - 1)))
    index = max(0, min(len(sorted_values) - 1, index))
    return sorted_values[index]


def run_level(url, token, concurrency, duration, timeout):
    """跑一轮：固定数量的工作线程，各自不停发请求，到时间就停。"""
    deadline = time.monotonic() + duration
    results = [None] * concurrency

    def worker(slot):
        latencies = []
        statuses = {}
        while time.monotonic() < deadline:
            status, ms = request_once(url, token, timeout)
            latencies.append(ms)
            statuses[status] = statuses.get(status, 0) + 1
        results[slot] = (latencies, statuses)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    latencies = []
    statuses = {}
    for slot_latencies, slot_statuses in results:
        latencies.extend(slot_latencies)
        for code, count in slot_statuses.items():
            statuses[code] = statuses.get(code, 0) + count

    total = len(latencies)
    ok = statuses.get(200, 0)
    latencies.sort()
    return {
        "total": total,
        "ok": ok,
        "errors": total - ok,
        "error_rate": (total - ok) / total if total else 0.0,
        "rps": total / duration if duration else 0.0,
        "p50": percentile(latencies, 50),
        "p95": percentile(latencies, 95),
        "p99": percentile(latencies, 99),
        "max": latencies[-1] if latencies else 0.0,
        "statuses": statuses,
    }


def main():
    parser = argparse.ArgumentParser(description="lab-agent 只读接口压测")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--path", action="append", default=None,
                        help="要压的路径，可写多次；默认三个只读接口")
    parser.add_argument("--concurrency", default="1,10,50",
                        help="并发数，逗号分隔，默认 1,10,50")
    parser.add_argument("--duration", type=float, default=10, help="每轮持续秒数")
    parser.add_argument("--warmup", type=float, default=2, help="每轮前预热秒数")
    parser.add_argument("--timeout", type=float, default=10, help="单请求超时秒数")
    parser.add_argument("--token", default="",
                        help="已有令牌；不传则用账号密码登录一次")
    parser.add_argument("--username", default=os.environ.get("BENCH_USERNAME", ""))
    parser.add_argument("--password", default=os.environ.get("BENCH_PASSWORD", ""))
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    paths = args.path or DEFAULT_PATHS
    levels = [int(x) for x in args.concurrency.split(",") if x.strip()]

    # 在 Windows 的 Git Bash 里跑时，`--path /api/xxx` 会被它自作主张改成
    # `G:/Git/api/xxx`（MSYS 把以 / 开头的参数当成 Unix 路径来翻译）。
    # 服务器是 Linux，不会有这个问题；这里直接拦下来，免得跑出一堆 100% 错误率
    # 还以为是服务器扛不住。
    for path in paths:
        if not path.startswith("/") or ":" in path:
            sys.exit(f"路径看起来被改写过：{path!r}\n"
                     f"应该形如 /api/lab/list?page=1&page_size=10。"
                     f"如果在 Windows 的 Git Bash 里跑，换 PowerShell 或到服务器上跑。")

    token = args.token
    if not token:
        if not args.username or not args.password:
            sys.exit("没有 --token 时，必须用 --username/--password "
                     "或环境变量 BENCH_USERNAME/BENCH_PASSWORD 提供账号")
        token = login(base, args.username, args.password, args.timeout)

    print(f"目标：{base}")
    print(f"Python {platform.python_version()} / {platform.platform()}")
    print(f"每轮 {args.duration:g} 秒，预热 {args.warmup:g} 秒，"
          f"每个请求新开连接（不复用）")
    print()

    rows = []
    for path in paths:
        url = base + path
        # 预热：让连接、数据库缓存、进程都进入稳定状态，预热数据不计入结果
        if args.warmup > 0:
            run_level(url, token, 1, args.warmup, args.timeout)

        for level in levels:
            result = run_level(url, token, level, args.duration, args.timeout)
            rows.append((path, level, result))
            print(f"{path}  并发 {level}")
            print(f"  请求 {result['total']}，成功 {result['ok']}，"
                  f"错误 {result['errors']}（{result['error_rate'] * 100:.2f}%）")
            print(f"  RPS {result['rps']:.1f}   p50 {result['p50']:.0f}ms   "
                  f"p95 {result['p95']:.0f}ms   p99 {result['p99']:.0f}ms   "
                  f"max {result['max']:.0f}ms")
            if result["statuses"]:
                shown = ", ".join(f"{code}:{count}"
                                  for code, count in sorted(result["statuses"].items()))
                print(f"  状态码 {shown}")
            if 429 in result["statuses"]:
                print("  ⚠️ 出现 429：触发限流了，这一行不能当作服务器能力的数字")
            print()

    print("Markdown（贴进 README 用）：")
    print("| 接口 | 并发 | RPS | p50 | p95 | p99 | 错误率 |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for path, level, result in rows:
        print(f"| `{path}` | {level} | {result['rps']:.1f} | "
              f"{result['p50']:.0f}ms | {result['p95']:.0f}ms | "
              f"{result['p99']:.0f}ms | {result['error_rate'] * 100:.2f}% |")


if __name__ == "__main__":
    main()
