from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, DateTime, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Mapped, mapped_column

from app.config import settings
from datetime import datetime

# hide_parameters 让 SQLAlchemy 不要在异常消息里带上绑定参数，
# 不然一旦有异常冒到日志或响应里，就等于把用户数据一起泄出去了。
engine = create_engine(settings.DATABASE_URL, hide_parameters=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Base(DeclarativeBase):
    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="主键ID", sort_order=-1
    )
    create_time: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, comment="创建时间"
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )


# 基线迁移的 revision id（migrations/versions/0001_initial_schema.py）。
# "已经建好表的库"第一次接入 Alembic 时会被登记到这一版，见下面 run_migrations。
BASELINE_REVISION = "0001"

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _recorded_revision(tables: set[str]) -> str | None:
    """alembic_version 里记着的版本号；表不存在**或者是空的**都返回 None。

    "空表"是真会出现的：upgrade 跑到一半失败（比如撞上 1050 table already exists）
    会留下一张建好了、却一行都没写进去的 alembic_version。所以判断"这个库接没接过
    Alembic"不能只看表在不在，得看里面有没有版本号。
    """
    if "alembic_version" not in tables:
        return None
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def run_migrations() -> None:
    """把数据库结构升到最新。应用启动时调用（见 app/main.py 的 lifespan）。

    取代了原来的 `Base.metadata.create_all`。区别在于 create_all 只会
    "建缺少的表"，给已有表加列、改列、加索引它一概不管，而且**不报错**——
    上次给 labs 加"周末时段"两列时就是这么卡住的，最后只能手工去 Navicat 跑 SQL。

    做三件事：
      1. 读 backend/alembic.ini（连接串由 migrations/env.py 从 app.config 取，
         ini 里那个是占位符，不生效）。
      2. **补登基线**：库里已经有表、却查不到版本号，说明这是个"接入 Alembic 之前
         就建好的库"（或者上次停在半路）。直接跑第一条迁移会撞 table already exists，
         所以先 stamp 到 0001（只写版本号，不执行任何 DDL），再从 0002 往后升。
         全新空库不会走这一步：它没有表，直接从头跑 0001 把表建出来。
      3. upgrade 到最新。

    ⚠️ 前提是**单进程**（Dockerfile 的 CMD 就是这么起的，刻意不加 --workers）。
    多 worker 同时启动时，每个进程都会走到这里，理论上会并发跑 DDL 而撞车。
    真要开多 worker，得先把这一步挪到部署流程里单独执行，或者用 MySQL 的
    GET_LOCK 包一层（reservation_service 里已有现成用法）。
    """
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # 不跑 alembic.ini 里那套日志配置：fileConfig 默认 disable_existing_loggers=True，
    # 会把 uvicorn 已经配好的 logger 全关掉，表现是"服务起来了但日志没了"。
    cfg.attributes["configure_logger"] = False

    tables = set(inspect(engine).get_table_names())
    # alembic_version 自己不算"业务表"：只有它一张表的库仍然是全新库。
    if tables - {"alembic_version"} and _recorded_revision(tables) is None:
        command.stamp(cfg, BASELINE_REVISION)

    command.upgrade(cfg, "head")
