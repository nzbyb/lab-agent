"""操作日志与登录日志。

两条不变式值得单独钉住：

1. 登录**失败**也要留痕。失败那条路会抛异常，业务事务全回滚，
   日志必须写在独立会话里才留得下。
2. 写日志本身绝不抛异常。审计是旁路，它挂了不能让审核通过跟着失败。
"""

from datetime import datetime, timedelta

from app.models.audit import AuditLog
from app.services import audit_service

LOGIN = "/api/auth/login"
REGISTER = "/api/auth/register"
LAB_COLLECTION = "/api/lab"
AUDIT_LIST = "/api/audit/list"
DEFAULT_PASSWORD = "pw123456"


def _fresh(db):
    """结束当前事务，好读到 HTTP 请求刚提交的行（MySQL REPEATABLE READ）。"""
    db.rollback()


def _only_log(db, **filters):
    _fresh(db)
    return db.query(AuditLog).filter_by(**filters).one()


class TestLoginLogs:
    def test_successful_login_is_logged(self, client, db, make_user):
        user = make_user(username="alice")

        assert (
            client.post(
                LOGIN, json={"username": "alice", "password": DEFAULT_PASSWORD}
            ).json()["code"]
            == 200
        )

        log = _only_log(db, action="login.success")
        assert log.category == "login"
        assert log.username == "alice"
        assert log.user_id == user.id
        # IP 由 main.py 的中间件塞进 ContextVar，服务层不用多传参数
        assert log.ip

    def test_failed_login_is_logged_even_for_unknown_user(self, client, db):
        """失败会抛异常、业务事务回滚——这条恰好证明日志没跟着回滚。"""
        body = client.post(
            LOGIN, json={"username": "ghost", "password": DEFAULT_PASSWORD}
        ).json()
        assert body["code"] == 400

        log = _only_log(db, action="login.failure")
        assert log.category == "login"
        assert log.username == "ghost"
        # 账号根本不存在，没有 user_id 可挂
        assert log.user_id is None
        assert log.detail == "账号或密码错误"

    def test_password_is_never_written_to_the_log(self, client, db, make_user):
        make_user(username="alice")
        client.post(LOGIN, json={"username": "alice", "password": "wrong-password"})
        client.post(LOGIN, json={"username": "alice", "password": DEFAULT_PASSWORD})

        _fresh(db)
        for log in db.query(AuditLog).all():
            assert "wrong-password" not in (log.detail or "")
            assert DEFAULT_PASSWORD not in (log.detail or "")


class TestOperationLogs:
    def test_register_is_logged(self, client, db):
        assert (
            client.post(
                REGISTER, json={"username": "newbie", "password": DEFAULT_PASSWORD}
            ).json()["code"]
            == 200
        )

        log = _only_log(db, action="user.register")
        assert log.category == "operation"
        assert log.username == "newbie"
        assert log.target_type == "user"
        assert log.detail == "自助注册"

    def test_admin_lab_create_is_logged_with_target(self, client, db, make_user, auth_headers):
        admin = make_user(username="boss", role="admin")

        body = client.post(
            LAB_COLLECTION,
            headers=auth_headers(admin),
            json={"name": "新实验室", "open_time": "08:00", "close_time": "18:00"},
        ).json()
        assert body["code"] == 200, body
        lab_id = body["data"]["id"]

        log = _only_log(db, action="lab.create")
        assert log.category == "operation"
        assert log.user_id == admin.id
        assert log.username == "boss"
        assert log.target_type == "lab"
        assert log.target_id == lab_id
        assert "新实验室" in log.detail


class TestAuditListApi:
    def _seed(self, db, make_user):
        _fresh(db)
        for index in range(3):
            audit_service.record(
                category=audit_service.CATEGORY_LOGIN,
                action="login.success",
                username=f"user{index}",
            )
        audit_service.record(
            category=audit_service.CATEGORY_OPERATION,
            action="lab.update",
            username="boss",
        )

    def test_admin_can_read_logs(self, client, db, make_user, auth_headers):
        admin = make_user(username="boss", role="admin")
        self._seed(db, make_user)

        body = client.get(AUDIT_LIST, headers=auth_headers(admin)).json()
        assert body["code"] == 200
        assert body["data"]["total"] == 4
        # 最新的在前
        assert body["data"]["list"][0]["action"] == "lab.update"

    def test_student_is_rejected(self, client, db, make_user, auth_headers):
        student = make_user(username="stu")
        self._seed(db, make_user)

        body = client.get(AUDIT_LIST, headers=auth_headers(student)).json()
        assert body["code"] == 403

    def test_anonymous_is_rejected(self, client):
        assert client.get(AUDIT_LIST).status_code == 401

    def test_filter_by_category(self, client, db, make_user, auth_headers):
        admin = make_user(username="boss", role="admin")
        self._seed(db, make_user)

        body = client.get(
            AUDIT_LIST, headers=auth_headers(admin), params={"category": "operation"}
        ).json()
        assert body["data"]["total"] == 1
        assert body["data"]["list"][0]["action"] == "lab.update"

    def test_filter_by_username_and_action(self, client, db, make_user, auth_headers):
        admin = make_user(username="boss", role="admin")
        self._seed(db, make_user)

        by_user = client.get(
            AUDIT_LIST, headers=auth_headers(admin), params={"username": "user1"}
        ).json()
        assert by_user["data"]["total"] == 1
        assert by_user["data"]["list"][0]["username"] == "user1"

        # action 是前缀/片段匹配："login" 能同时命中 login.success / login.failure
        by_action = client.get(
            AUDIT_LIST, headers=auth_headers(admin), params={"action": "login"}
        ).json()
        assert by_action["data"]["total"] == 3

    def test_filter_by_date(self, db):
        audit_service.record(category="login", action="login.success", username="u")
        today = datetime.now().strftime("%Y-%m-%d")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        _fresh(db)
        assert audit_service.get_log_page_list(db, start_date=today, end_date=today).total == 1
        # 结束日包含整天：只传今天当结束日，今天的日志也得筛得出来
        assert audit_service.get_log_page_list(db, end_date=today).total == 1
        assert audit_service.get_log_page_list(db, start_date=tomorrow).total == 0


class TestAuditNeverBreaksBusiness:
    def test_record_swallows_its_own_failure(self, monkeypatch):
        """数据库/日志出问题时，写日志必须静默失败，不能把调用方拖下去。"""

        def broken_session():
            raise RuntimeError("数据库不可用")

        monkeypatch.setattr(audit_service, "SessionLocal", broken_session)
        audit_service.record(category="login", action="login.success", username="x")
