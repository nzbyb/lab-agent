import asyncio
from contextlib import asynccontextmanager
import traceback

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from app.config import ALLOWED_ORIGINS, UPLOAD_DIR

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
from app.services import kb_service, reservation_service  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 建表/升级必须排在 warmup 前面：warmup 会读 labs 表渲染知识库的「开放时间.md」，
    # 全新库里表还没建出来，顺序反了就第一次启动必报错。
    # 放在 lifespan 里而不是模块顶层：模块顶层是"import 就改数据库"，
    # 测试导入 app.main 时也会顺带执行（tests/conftest.py 刻意绕开 lifespan）。
    await asyncio.to_thread(run_migrations)
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
