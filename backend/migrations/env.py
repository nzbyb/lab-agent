"""Alembic 运行环境。

两件事跟默认生成的版本不一样，都是刻意的：

1. **连接串不写在 alembic.ini 里**，而是从 `app.config.settings` 取。
   项目里已经有唯一的配置来源（backend/.env），再在 ini 里抄一份，
   迟早会出现"改了 .env 没改 ini"的排查事故。而且 ini 是要提交到公开仓库的，
   里面绝不能有真连接串。

2. **导入全部模型**。`target_metadata` 只有把模型都挂上，autogenerate 才看得见；
   少 import 一个模型，它就会被当成"数据库里多出来的表"，生成一条 DROP TABLE。
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.database import Base

# 下面这些 import 是给 autogenerate 看的，不要删（跟 app/main.py 建表那段同一个道理）
from app.models.user import User  # noqa: F401
from app.models.lab import Lab  # noqa: F401
from app.models.equipment import Equipment  # noqa: F401
from app.models.reservation import Reservation  # noqa: F401
from app.models.chat import ChatConversation, ChatMessage  # noqa: F401
from app.models.verification import VerificationCode  # noqa: F401
from app.models.notification import Notification  # noqa: F401

config = context.config

# 应用启动时会在进程里直接调 Alembic（见 app/database.py 的 run_migrations）。
# 那种情况下**不能**跑 fileConfig —— 它默认 disable_existing_loggers=True，
# 会把 uvicorn 已经配好的 logger 全部关掉，表现是"服务起来了但日志没了"。
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

# 从代码里拿连接串，而不是从 ini
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # 让 autogenerate 能发现"列的类型改了"（默认只比对增删列）
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
