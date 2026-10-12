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

# ---------------------------------------------------------------------------
# 以上必须早于以下所有 import
# ---------------------------------------------------------------------------
from datetime import datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402

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

from app.limiter import limiter  # noqa: E402
from app.main import app  # noqa: E402
from app.models.equipment import Equipment  # noqa: E402
from app.models.lab import Lab  # noqa: E402
from app.models.reservation import Reservation  # noqa: E402,F401
from app.models.chat import ChatConversation, ChatMessage  # noqa: E402,F401
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
    Base.metadata.create_all(bind=engine)
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
    def _make(username="stu1", password=DEFAULT_PASSWORD, role="student", status=1):
        user = User(
            username=username,
            password=hash_password(password),
            name=username,
            role=role,
            status=status,
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
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}

    return _make
