"""接口限流。

单独放一个模块是为了避开循环导入：main.py 要注册 limiter，
api/auth.py 要用它装饰路由，两边都从这儿拿同一个实例。

存储用 slowapi 默认的内存计数器——**只对单进程部署有效**。
uvicorn 开多个 worker 时每个进程各算各的，实际额度会翻倍。
本项目是单进程起的，够用；真要精确（多实例部署）得换 Redis 后端，
但为了这点需求引入 Redis 属于过度设计，写在这里当已知边界。
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
