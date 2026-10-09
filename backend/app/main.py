import asyncio
from contextlib import asynccontextmanager
import traceback

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from app.config import UPLOAD_DIR

from app.database import engine, Base
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
from app.models.user import User
from app.models.lab import Lab  # noqa: F401  必须导入，否则建表时发现不了模型
from app.models.equipment import Equipment
from app.models.reservation import (
    Reservation,
)
from app.services import (
    kb_service,
    reservation_service,
)  # noqa: F401  必须导入，否则建表时发现不了模型


@asynccontextmanager
async def lifespan(app: FastAPI):
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

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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

Base.metadata.create_all(bind=engine)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


@app.get("/")
def root():
    return {"message": "FastAPI is running!"}
