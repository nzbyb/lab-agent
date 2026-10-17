"""限流计数后端（内存 / Redis）的单元测试。

这里**不需要真的起一个 Redis**：
- 造 Redis 版 limiter 时只是拿到存储对象，redis-py 是懒连接的；
- "Redis 连不上怎么办"那条，连的是 127.0.0.1:1 这种必定被拒的端口，
  正好模拟容器挂掉时"连接被拒"的情形。
"""

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from limits.storage import MemoryStorage, RedisStorage

from app.limiter import build_limiter


def test_empty_url_falls_back_to_memory():
    """没配 REDIS_URL 时用进程内存——本机开发和测试都走这条。"""
    limiter = build_limiter("")
    assert isinstance(limiter._storage, MemoryStorage)


def test_redis_url_selects_redis_storage():
    """配了 REDIS_URL 就用 Redis 存储（构造时不会连网）。"""
    limiter = build_limiter("redis://127.0.0.1:6379/0")
    assert isinstance(limiter._storage, RedisStorage)

    # 超时必须真的传进去了：Redis 假死时它决定一个请求最多卡多久，
    # 而这行代码删掉不会有任何状态码变化（只是变慢），只能靠这里盯住。
    kwargs = limiter._storage.storage.connection_pool.connection_kwargs
    assert kwargs["socket_connect_timeout"] == 0.1
    assert kwargs["socket_timeout"] == 0.1


def test_redis_unreachable_degrades_to_memory():
    """Redis 连不上时退回进程内存继续限流——既不 500，也不放开额度。

    端口 1 上没有服务，连接会被立刻拒绝。实测 slowapi 的行为是：
    把计数器换成本进程的 MemoryStorage，**额度照旧生效**（不是"不限流"）。
    所以这里断言的是：前 5 次 200，第 6 次起 429，全程没有 500。
    """
    limiter = build_limiter("redis://127.0.0.1:1/0")

    app = FastAPI()
    app.state.limiter = limiter

    @app.get("/ping")
    @limiter.limit("5/minute")
    def ping(request: Request):
        return {"ok": True}

    client = TestClient(app)
    codes = [client.get("/ping").status_code for _ in range(8)]

    assert 500 not in codes, f"Redis 挂掉不该变成服务端错误，实际拿到：{codes}"
    assert codes[:5] == [200] * 5, f"额度内应当放行，实际拿到：{codes}"
    assert codes[5:] == [429] * 3, f"额度用完后应当仍然限流，实际拿到：{codes}"


def test_module_limiter_follows_settings():
    """全局那个 limiter 真的按 REDIS_URL 接线了吗？

    其它用例都被 conftest 钉成内存存储，这一行接线本身没人测过——把它改回
    `Limiter(key_func=...)` 全量测试照样全绿。用子进程跑，是因为在测试进程里
    reload 模块会造出第二个 limiter，而路由上挂的还是旧的，会污染后面的用例。
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[1]
    env = dict(os.environ, REDIS_URL="redis://127.0.0.1:6379/0")
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.limiter import limiter; print(type(limiter._storage).__name__)",
        ],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"子进程导入失败：{proc.stderr}"
    assert proc.stdout.strip() == "RedisStorage"
