"""接口限流。

单独放一个模块是为了避开循环导入：main.py 要注册 limiter，
api/auth.py 要用它装饰路由，两边都从这儿拿同一个实例。

计数存哪儿由配置 `REDIS_URL` 决定：

- 填了（Docker 部署里 compose 默认填 `redis://redis:6379/0`）→ 计数在 Redis，
  多个进程/多实例共用一份，后端重启也不清零。
- 留空（本机直接跑 uvicorn、跑测试）→ **显式**用进程内存，不用额外起 Redis。

**Redis 连不上时退回进程内存继续限流，不报错**（`in_memory_fallback_enabled` +
`swallow_errors`）：限流是保护措施，不该因为它自己挂了把整站拖垮——所以绝不返回 500。
注意这里的实际行为（实测过，别想当然）：**不是"不限流"，而是换成本进程的内存计数器，
额度照旧**。本项目是单进程，所以 Redis 挂了以后效果跟换 Redis 之前一模一样；
真上了多实例，那段时间会变成"每台各算一份"，属于可接受的降级。

降级不是静默的：见文件末尾 `_enable_slowapi_logs`。不加那几行，
slowapi 的警告会被它自己挂的"黑洞" handler 吃掉，`docker compose logs` 里一个字都没有。
"""

import logging

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

# Redis 不可达时别让请求卡在 TCP 超时上：容器停掉是"连接被拒"（立刻返回），
# 网络分区、服务假死才会卡住，这两个超时是兜底。
# 取 0.1 秒而不是 0.5：限流检查在事件循环里**同步**执行（AI 那条流式接口是 async），
# 卡多久整个进程的所有请求就顿多久。同机同网络的 Redis 正常是亚毫秒级，0.1 秒够用。
_STORAGE_OPTIONS = {"socket_connect_timeout": 0.1, "socket_timeout": 0.1}


def build_limiter(redis_url: str = "") -> Limiter:
    """按配置造一个 limiter。

    抽成函数是为了测试能分别造"内存版"和"Redis 版"——后者构造时只拿到存储对象，
    并不连网，所以不需要真的起一个 Redis。真正在用的那个实例在文件末尾，
    名字仍然叫 `limiter`，别处照旧 `from app.limiter import limiter`。
    """
    common = {
        "key_func": get_remote_address,
        # Redis 挂了退回进程内存继续限流，不返回 500（详见文件开头的说明）
        "in_memory_fallback_enabled": True,
        "swallow_errors": True,
    }
    if not redis_url:
        # 必须显式写 memory://。不传的话 slowapi 会退回去读环境变量
        # RATELIMIT_STORAGE_URL，"留空"就不再等于"一定用内存"——测试环境尤其
        # 不能留这个口子：那儿每个用例都会 reset()，连上线上 Redis 就会删它的限流键。
        return Limiter(**common, storage_uri="memory://")

    return Limiter(
        **common,
        storage_uri=redis_url,
        storage_options=dict(_STORAGE_OPTIONS),
    )


class _DropExceededWarnings(logging.Filter):
    """丢掉 slowapi 每拦一个请求就打的 "ratelimit ... exceeded"。

    这条是每个 429 一行。放出去等于把日志变成放大器：别人刷你的接口，
    你这边日志跟着涨，而 Docker 默认的日志文件没有上限。429 本身已经够说明问题了。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return not str(record.getMessage()).startswith("ratelimit ")


def _enable_slowapi_logs() -> None:
    """让 slowapi 的警告真正打得出来。

    slowapi 在构造 Limiter 时会给名为 "slowapi" 的 logger 挂一个 emit 什么都不做的
    handler（见 extension.py 里的 BlackHoleHandler），而 uvicorn 的默认日志配置只配了
    uvicorn.* 几个 logger、不给 root 挂 handler。两者一叠加，限流降级的警告默认哪儿
    都不去——Redis 悄悄挂了，你在 docker logs 里什么都看不到。
    """
    logger = logging.getLogger("slowapi")
    if any(getattr(h, "_lab_agent_handler", False) for h in logger.handlers):
        return  # 模块被 reload 过，别重复添加
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     slowapi: %(message)s"))
    handler.addFilter(_DropExceededWarnings())
    handler._lab_agent_handler = True  # type: ignore[attr-defined]
    logger.addHandler(handler)


limiter = build_limiter(settings.REDIS_URL)
_enable_slowapi_logs()
