from contextlib import contextmanager
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


@contextmanager
def _migration_lock():
    """同一台 MySQL 上，同一时刻只让一个进程跑迁移。

    正常部署由 compose 的 migrate 服务单独跑一次，本来不会并发。这层锁是给
    「有人图省事在 lifespan 里打开了 AUTO_MIGRATE」和「多副本同时启动」兜底的：
    两个进程同时 upgrade，最容易撞上 1050 table already exists，留下半截结构。

    锁名带库名：测试库和正式库常常在同一台 MySQL 上，不带库名的话
    跑测试会平白挡住正式库的迁移。
    """
    if engine.dialect.name != "mysql":
        yield
        return
    name = f"lab_agent:migrate:{engine.url.database}"
    conn = engine.connect()
    try:
        acquired = conn.execute(
            text("SELECT GET_LOCK(:name, 60)"), {"name": name}
        ).scalar()
        if acquired != 1:
            raise RuntimeError("等待数据库迁移锁超时，可能有另一个进程正在迁移")
        yield
    finally:
        try:
            conn.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": name})
        finally:
            conn.close()


def run_migrations() -> None:
    """把数据库结构升到最新。

    **正常部署不在应用启动时调用**：compose 里有一个一次性的 `migrate`
    服务专门跑 `python -m app.migrate`，跑完 backend 才启动（见 docker-compose.yml）。
    这样多 worker/多副本同时启动时不会各自跑一遍 DDL。本机开发照样可以
    `python -m app.migrate`，或在 .env 里设 AUTO_MIGRATE=true 让 lifespan 代跑。

    测试库不走 lifespan，由 tests/conftest.py 直接调用本函数，保证测试库结构
    跟迁移一致。

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
    """
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # 不跑 alembic.ini 里那套日志配置：fileConfig 默认 disable_existing_loggers=True，
    # 会把 uvicorn 已经配好的 logger 全关掉，表现是"服务起来了但日志没了"。
    cfg.attributes["configure_logger"] = False

    with _migration_lock():
        tables = set(inspect(engine).get_table_names())
        # alembic_version 自己不算"业务表"：只有它一张表的库仍然是全新库。
        if tables - {"alembic_version"} and _recorded_revision(tables) is None:
            command.stamp(cfg, BASELINE_REVISION)

        command.upgrade(cfg, "head")
