import asyncio
from contextlib import asynccontextmanager
import traceback

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from app.config import ALLOWED_ORIGINS, UPLOAD_DIR, settings

from app.database import run_migrations
from app.api import api
from starlette.middleware.cors import CORSMiddleware
from app.common.exceptions import (
    BusinessException,
    business_exception_hadler,
    http_exception_hadler,
    validation_exception_hadler,
    rate_limit_exception_hadler,
    global_exception_hadler,
)
from app.limiter import limiter
# 下面这几个 import 现在**不再是建表用的**——建表已经交给 Alembic
# （见 app/database.py 的 run_migrations）。保留是有意的：它们让"任何 import app.main
# 的入口"都拿到完整的 Base.metadata，而不是依赖 app.api 恰好把每个模型都带进来这个巧合。
from app.models.user import User  # noqa: F401
from app.models.lab import Lab  # noqa: F401
from app.models.equipment import Equipment  # noqa: F401
from app.models.reservation import Reservation  # noqa: F401
from app.models.chat import ChatConversation, ChatMessage  # noqa: F401
from app.models.verification import VerificationCode  # noqa: F401
from app.models.notification import Notification  # noqa: F401
from app.services import kb_service, reservation_service  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 正常部署**不在这里建表**：compose 的 migrate 服务会先跑 python -m app.migrate，
    # backend 通过 depends_on: service_completed_successfully 等它成功。
    # 这样多 worker/多副本同时启动时不会各跑一遍 DDL，也不会出现"两个进程抢着
    # ALTER TABLE、一个成功一个撞 1050"的半截状态。
    #
    # AUTO_MIGRATE 只给本机开发留的后门，默认 false。真打开也不会裸奔：
    # run_migrations 里有 MySQL GET_LOCK，多进程会排队。
    if settings.AUTO_MIGRATE:
        await asyncio.to_thread(run_migrations)
    # warmup 会读 labs 表渲染知识库的「开放时间.md」，所以必须等表建好再跑。
    try:
        await asyncio.to_thread(kb_service.warmup)
    except Exception:
        traceback.print_exc()
    task = asyncio.create_task(reservation_service.run_expire_scan())
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def _init_sentry() -> None:
    """DSN 留空就什么都不做。

    刻意把 import 放在判断里面：没配 Sentry 的环境（本机、测试、CI）根本
    不会加载这个包，也就不会因为没装它而启动失败。配了 DSN 但忘了装依赖时，
    只打印异常、不阻止服务启动——错误监控挂了不该让整个站点跟着挂。

    不发送请求体：登录接口的 body 里有明文密码，Sentry 默认会带一部分请求信息，
    这里明确关掉，只留错误堆栈和 URL。
    """
    if not settings.SENTRY_DSN:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    except ImportError:
        traceback.print_exc()
        return
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.SENTRY_ENVIRONMENT,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        integrations=[FastApiIntegration(), SqlalchemyIntegration()],
        send_default_pii=False,
        max_request_body_size="never",
    )


_init_sentry()

# Sentry 要在创建 app 之前 init，FastAPI 集成才会挂到之后创建的 app 上。
app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api)

app.add_exception_handler(BusinessException, business_exception_hadler)
app.add_exception_handler(HTTPException, http_exception_hadler)
app.add_exception_handler(RequestValidationError, validation_exception_hadler)
app.add_exception_handler(Exception, global_exception_hadler)

# slowapi 要靠 app.state.limiter 找计数器；漏了这行被装饰的路由会在运行时报错
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exception_hadler)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


@app.get("/")
def root():
    return {"message": "FastAPI is running!"}
