"""pytest 全局配置。

核心原则：所有测试都跑在独立的 lab_agent_test 库上，绝不碰线上的 lab_agent。

做法是在 import 任何 app 模块之前，用环境变量 DATABASE_URL 覆盖 .env 里的值。
pydantic-settings 的优先级是「环境变量 > .env 文件」，所以这样能盖掉。
app/database.py 在模块级执行 create_engine(settings.DATABASE_URL)，
所以覆盖必须发生在那次 import 之前。
"""

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import text
from sqlalchemy.engine import make_url


def _read_dotenv(key: str) -> str | None:
    env_file = BACKEND_DIR / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key:
            return value.strip()
    return None


_real_url = _read_dotenv("DATABASE_URL")
if not _real_url:
    raise RuntimeError("backend/.env 里没有 DATABASE_URL，测试无法启动")

_test_url = make_url(_real_url).set(database="lab_agent_test")

# 保险丝：库名必须以 _test 结尾。宁可测试跑不起来，也不能误删线上数据。
if not (_test_url.database or "").endswith("_test"):
    raise RuntimeError(f"拒绝在非测试库上运行测试：{_test_url.database!r}")

os.environ["DATABASE_URL"] = _test_url.render_as_string(hide_password=False)

# 限流计数强制走内存，测试绝不能连到线上 Redis：
# 下面那个 _reset_rate_limiter 每个用例都会调 limiter.reset()，而 Redis 后端的
# reset() 会删掉整个库里的限流键——不丢业务数据，但会让线上限流短暂失效。
# 想验证 Redis 那条路，用单独的用例自己造 limiter（见 test_limiter_storage.py）。
os.environ["REDIS_URL"] = ""
# slowapi 在不传 storage_uri 时会去读这个变量；留着它等于给上面那句开了个后门。
os.environ.pop("RATELIMIT_STORAGE_URL", None)

# 测试绝不发真实邮件。本机 .env 可能配了真实的 SMTP 授权码，而预约审核
# 现在会顺带发通知邮件——不清空的话，跑一次用例就会给库里的测试邮箱发信。
# 需要验证邮件内容的用例自己 monkeypatch notification_service.mailer。
os.environ["SMTP_HOST"] = ""
os.environ["SMTP_USER"] = ""
os.environ["SMTP_PASSWORD"] = ""

# ---------------------------------------------------------------------------
# 以上必须早于以下所有 import
# ---------------------------------------------------------------------------
from datetime import datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine, run_migrations  # noqa: E402

# ---------------------------------------------------------------------------
# 第二道保险丝：查 engine 真正连上的库，而不是我们以为改成的库名。
#
# 上面那句 set(database="lab_agent_test") 只改了 URL 字符串。如果 app.database
# 在更早的时候就已经被 import 过（`pytest -p <插件>` 加载插件早于 conftest，
# 插件里任何一句 import app.xxx 都会触发），create_engine 已经按 .env 建好了，
# 模块进了 sys.modules 就不会再建第二次——那上面那句 os.environ 覆盖等于没写，
# 这里的 engine 连的还是生产库，后面 _truncate_all 清的就是真数据。
# 这事已经真实发生过一次，所以必须校验 engine 本身。
# ---------------------------------------------------------------------------
if not (engine.url.database or "").endswith("_test"):
    raise RuntimeError(
        f"engine 实际连的是 {engine.url.database!r}，不是测试库，拒绝运行测试。"
        "（多半是被 import 得太早，DATABASE_URL 覆盖没赶上 create_engine）"
    )

from limits.storage import MemoryStorage  # noqa: E402

from app.limiter import limiter  # noqa: E402

# ---------------------------------------------------------------------------
# 第二道保险丝（限流版）：查 limiter **真正**用的存储，而不是我们以为的。
#
# 上面那两句 os.environ 覆盖跟数据库那条一样，只是"我们以为"：如果 app.limiter
# 被更早地 import 过（`pytest -p <插件>`），或者环境里另设了 RATELIMIT_STORAGE_URL，
# limiter 可能已经连上了别的 Redis。而下面的 _reset_rate_limiter 每个用例都会
# reset()，Redis 后端的 reset() 会删掉那个库里的限流键。
# ---------------------------------------------------------------------------
if not isinstance(limiter._storage, MemoryStorage):
    raise RuntimeError(
        f"限流器实际用的是 {type(limiter._storage).__name__}，不是内存存储，拒绝运行测试。"
        "（多半是 REDIS_URL / RATELIMIT_STORAGE_URL 被设上了）"
    )

from app.main import app  # noqa: E402
from app.models.equipment import Equipment  # noqa: E402
from app.models.lab import Lab  # noqa: E402
from app.models.reservation import Reservation  # noqa: E402,F401
from app.models.chat import ChatConversation, ChatMessage  # noqa: E402,F401
from app.models.verification import VerificationCode  # noqa: E402,F401
from app.models.user import User  # noqa: E402
from app.schemas.reservation import ReservationCreateRequest  # noqa: E402
from app.services import kb_service  # noqa: E402
from app.utils.password import hash_password  # noqa: E402
from app.utils.jwt import create_access_token  # noqa: E402

DEFAULT_PASSWORD = "pw123456"


def _truncate_all() -> None:
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f"TRUNCATE TABLE `{table.name}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


@pytest.fixture(scope="session", autouse=True)
def _database_schema():
    """测试库的表结构**走迁移**，不用 create_all。

    原来这里是 `Base.metadata.create_all`，它只建"缺的表"，给已有表**加列一概不管**。
    测试库 lab_agent_test 是一张长期存在的库，于是"模型加了列、测试库没这列"的表现是
    整片用例报 Unknown column；而 CI 里库是新建的、create_all 会带上新列——于是
    "CI 绿、本机红"，最难查的那种。

    换成跑迁移之后：测试库跟迁移对齐，模型和迁移一旦对不上（忘了写迁移，或迁移写错）
    测试会当场红。CI 顺带成了"迁移写错"的拦截网——在此之前它完全拦不住。

    注意这仍然要求测试库**已经存在**（迁移只建表，不建库），见 README 里那句
    "跑之前要另建一个空库"。
    """
    run_migrations()
    yield


@pytest.fixture(autouse=True)
def _clean_database():
    """每个用例前后清空数据，用例之间互不影响"""
    _truncate_all()
    yield
    _truncate_all()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """限流计数器是进程内、跨用例共享的状态，必须跟着用例一起重置。

    不重置的话前面的用例会把登录额度耗光，后面的用例一登录就吃 429，
    变成「单跑绿、整套跑红」的假故障。
    """
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(autouse=True)
def _isolate_knowledge_base(tmp_path, monkeypatch):
    """把知识库和向量库目录挪到临时目录。

    管理端增删改实验室会重新生成 data/kb/开放时间.md。不挪的话，用例里的
    测试数据会把仓库里那份真实文档覆盖掉，git status 里就凭空多出一处改动，
    而且下次跑测试又变一次。向量库目录一起挪——索引指纹存在那里，跟着走
    才不会串。
    """
    monkeypatch.setattr(kb_service, "KB_DIR", tmp_path / "kb")
    monkeypatch.setattr(kb_service, "CHROMA_DIR", tmp_path / "chroma")


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    # 故意不用 `with TestClient(app)`：那会触发 lifespan，
    # 进而去加载 KB 向量库的 embedding 模型，测试会变得非常慢。
    # 直接发请求不会执行 lifespan。
    return TestClient(app)


@pytest.fixture
def make_user(db):
    def _make(
        username="stu1",
        password=DEFAULT_PASSWORD,
        role="student",
        status=1,
        name=None,
        email=None,
        phone=None,
    ):
        user = User(
            username=username,
            password=hash_password(password),
            name=name or username,
            role=role,
            status=status,
            email=email,
            phone=phone,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    return _make


@pytest.fixture
def make_lab(db):
    def _make(
        name="计算机实验室",
        open_time="08:00",
        close_time="21:00",
        status=1,
        weekend_open_time=None,
        weekend_close_time=None,
    ):
        """默认造一间**天天都开**的实验室。

        周末两列默认跟着周中走（而不是留空），是因为 `booking` 夹具默认约"明天"：
        要是周末留空 = 周末不开放，那么每逢周五、周六跑测试，一堆用例都会因为
        "当天不开放"而红——**只在周末红**，是最难查的那种。想测"周末不开放"的用例
        自己显式传 weekend_open_time="" 或钉一个周六的日期。

        跟周中派生而不是写死 21:00：`make_lab(close_time="18:00")` 之后，
        周末也得是 18:00 关门，否则那条"晚于关闭时间"的用例会在周末悄悄放行。
        """
        lab = Lab(
            name=name,
            description=name,
            location="综合实验楼201",
            capacity=40,
            open_time=open_time,
            close_time=close_time,
            weekend_open_time=open_time if weekend_open_time is None else weekend_open_time,
            weekend_close_time=close_time if weekend_close_time is None else weekend_close_time,
            status=status,
        )
        db.add(lab)
        db.commit()
        db.refresh(lab)
        return lab

    return _make


@pytest.fixture
def make_equipment(db):
    def _make(lab_id, name="RTX4090", status=1, quantity=2):
        eq = Equipment(lab_id=lab_id, name=name, quantity=quantity, status=status)
        db.add(eq)
        db.commit()
        db.refresh(eq)
        return eq

    return _make


@pytest.fixture
def booking():
    """造预约请求体。默认约"明天"，避开"开始时间不能早于当前时间"的校验。"""

    def _make(
        lab_id,
        date=None,
        start_time="09:00",
        end_time="10:00",
        equipment_id=None,
        remark=None,
    ):
        if date is None:
            date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        return ReservationCreateRequest(
            lab_id=lab_id,
            equipment_id=equipment_id,
            date=date,
            start_time=start_time,
            end_time=end_time,
            remark=remark,
        )

    return _make


@pytest.fixture
def auth_headers():
    """给某个用户签一个真 token，用来打需要登录的 HTTP 接口"""

    def _make(user):
        # 令牌里必须带上用户当前的版本号，否则签出来的令牌会被
        # dependencies/auth.py 的版本比对拒掉，全部鉴权用例一起红。
        return {
            "Authorization": (
                f"Bearer {create_access_token(user.id, user.token_version or 0)}"
            )
        }

    return _make
