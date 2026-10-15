"""鉴权与权限矩阵。

三件事：
1. 注册 / 登录自身的规则
2. token 的校验——伪造的、过期的、用户被删或被禁用的
3. 谁能碰哪些接口：学生不能访问管理员接口

注意本项目的一个反直觉设计：BusinessException 一律包成 HTTP 200 返回，
真正的错误码在 body 的 code 字段里。所以下面几处权限用例断言的是
「HTTP 200 + body.code == 403」。这是刻意为之，前端就是靠 body.code 判断的，
不要"顺手修正"成 HTTP 403。
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import settings
from app.models.user import User

REGISTER = "/api/auth/register"
LOGIN = "/api/auth/login"
ME = "/api/user/me"
USER_LIST = "/api/user/list"
USER_COLLECTION = "/api/user"


def _fresh(db):
    """结束当前事务，好读到其它连接刚提交的数据（MySQL 默认为 REPEATABLE READ）"""
    db.rollback()


class TestRegister:
    def test_register_success(self, client, db):
        resp = client.post(
            REGISTER, json={"username": "newbie", "password": "pw123456"}
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 200

        _fresh(db)
        assert db.query(User).filter(User.username == "newbie").first() is not None

    def test_duplicate_username_rejected(self, client, make_user):
        make_user(username="taken")
        resp = client.post(
            REGISTER, json={"username": "taken", "password": "pw123456"}
        )
        assert resp.json()["code"] == 400
        assert resp.json()["message"] == "账号已存在"

    def test_register_cannot_escalate_to_admin(self, client, db):
        """注册接口的请求体里没有 role 字段，多塞一个也应该被忽略"""
        resp = client.post(
            REGISTER,
            json={"username": "hacker", "password": "pw123456", "role": "admin"},
        )
        assert resp.json()["code"] == 200

        _fresh(db)
        created = db.query(User).filter(User.username == "hacker").first()
        assert created is not None
        assert created.role == "student", "注册接口不得被用来创建管理员"

    def test_name_defaults_to_username(self, client, db):
        client.post(REGISTER, json={"username": "nobody", "password": "pw123456"})
        _fresh(db)
        created = db.query(User).filter(User.username == "nobody").first()
        assert created.name == "nobody"

    def test_password_is_never_stored_in_plaintext(self, client, db):
        client.post(REGISTER, json={"username": "secret", "password": "pw123456"})
        _fresh(db)
        created = db.query(User).filter(User.username == "secret").first()
        assert created.password != "pw123456"
        assert created.password.startswith("$2"), "密码应当以 bcrypt 哈希形式存储"


class TestLogin:
    def test_login_success(self, client, make_user):
        make_user(username="alice", password="pw123456")
        resp = client.post(LOGIN, json={"username": "alice", "password": "pw123456"})
        body = resp.json()
        assert body["code"] == 200
        assert body["message"] == "登录成功"
        assert body["data"]["token"]
        assert body["data"]["user"]["username"] == "alice"
        assert "password" not in body["data"]["user"], "响应里不能带出密码字段"

    def test_wrong_password_rejected(self, client, make_user):
        make_user(username="alice", password="pw123456")
        resp = client.post(LOGIN, json={"username": "alice", "password": "wrong"})
        # 业务错误统一是 400。原来这里是 500，而 500 的含义是"服务器自己出故障了"，
        # 密码输错报 500 会把排查的人往错的方向带；500 现在只留给全局兜底那条路。
        assert resp.json()["code"] == 400
        assert resp.json()["message"] == "账号或密码错误"

    def test_unknown_user_rejected(self, client):
        resp = client.post(LOGIN, json={"username": "ghost", "password": "pw123456"})
        assert resp.json()["code"] == 400
        assert resp.json()["message"] == "账号或密码错误"

    def test_unknown_user_and_wrong_password_are_indistinguishable(
        self, client, make_user
    ):
        """两者返回同一句话，避免攻击者拿它枚举出哪些账号真实存在"""
        make_user(username="alice", password="pw123456")
        wrong_pw = client.post(
            LOGIN, json={"username": "alice", "password": "wrong"}
        ).json()
        no_such = client.post(
            LOGIN, json={"username": "ghost", "password": "pw123456"}
        ).json()
        assert wrong_pw["message"] == no_such["message"]
        assert wrong_pw["code"] == no_such["code"]

    def test_disabled_account_rejected(self, client, make_user):
        make_user(username="frozen", password="pw123456", status=0)
        resp = client.post(LOGIN, json={"username": "frozen", "password": "pw123456"})
        assert resp.json()["message"] == "账号被禁用"


class TestTokenValidation:
    def test_valid_token_passes(self, client, make_user, auth_headers):
        user = make_user(username="alice")
        resp = client.get(ME, headers=auth_headers(user))
        assert resp.status_code == 200
        assert resp.json()["data"]["username"] == "alice"

    def test_missing_token_rejected(self, client):
        resp = client.get(ME)
        assert resp.status_code == 401
        assert resp.json()["code"] == 401

    def test_garbage_token_rejected(self, client):
        resp = client.get(ME, headers={"Authorization": "Bearer not-a-real-token"})
        assert resp.status_code == 401
        assert resp.json()["message"] == "登录已失效，请重新登录"

    def test_token_signed_with_foreign_secret_rejected(self, client, make_user):
        """换个密钥签出来的 token 必须被拒——否则等于谁都能伪造身份"""
        user = make_user(username="alice")
        forged = jwt.encode(
            {
                "user_id": user.id,
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            "attacker-secret-attacker-secret-attacker",
            algorithm="HS256",
        )
        resp = client.get(ME, headers={"Authorization": f"Bearer {forged}"})
        assert resp.status_code == 401

    def test_expired_token_rejected(self, client, make_user):
        user = make_user(username="alice")
        # 这里必须用 aware 时间：naive datetime 会被 PyJWT 当成 UTC，
        # 在 UTC+8 上"1 小时前"其实落到了未来 7 小时。
        expired = jwt.encode(
            {
                "user_id": user.id,
                "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            },
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )
        resp = client.get(ME, headers={"Authorization": f"Bearer {expired}"})
        assert resp.status_code == 401

    def test_token_of_deleted_user_rejected(self, client, db, make_user, auth_headers):
        """用户被删掉后，他手里的旧 token 必须立刻失效，而不是报 500"""
        user = make_user(username="gone")
        headers = auth_headers(user)
        user_id = user.id

        _fresh(db)
        db.query(User).filter(User.id == user_id).delete()
        db.commit()

        resp = client.get(ME, headers=headers)
        assert resp.status_code == 401
        assert resp.json()["message"] == "用户不存在"

    def test_token_of_disabled_user_rejected(self, client, db, make_user, auth_headers):
        """用户被禁用后，旧 token 同样要立刻失效"""
        user = make_user(username="alice")
        headers = auth_headers(user)
        user_id = user.id

        _fresh(db)
        db.query(User).filter(User.id == user_id).update({User.status: 0})
        db.commit()

        resp = client.get(ME, headers=headers)
        assert resp.status_code == 401
        assert resp.json()["message"] == "用户被禁用"


class TestPermissionMatrix:
    """学生不能碰任何管理员接口。

    注意断言的写法：HTTP 状态码是 200，权限错误体现在 body.code == 403。
    """

    ADMIN_CALLS = [
        ("GET", USER_LIST, None),
        ("POST", USER_COLLECTION, {"username": "x", "password": "pw123456"}),
        ("PUT", "/api/user/1", {"name": "x"}),
        # 重置他人密码是提权最狠的一条：拿到它就能直接接管任何账号。
        # 请求体刻意是合法的（密码长度合规），这样它要是在权限上漏了，
        # 失败原因只可能是权限，不会跟参数校验混在一起。
        ("PUT", "/api/user/1/password", {"new_password": "pw123456"}),
        ("DELETE", "/api/user/1", None),
    ]

    @pytest.mark.parametrize("method,url,payload", ADMIN_CALLS)
    def test_student_denied_on_admin_endpoints(
        self, client, make_user, auth_headers, method, url, payload
    ):
        student = make_user(username="stu", role="student")
        resp = client.request(method, url, headers=auth_headers(student), json=payload)
        assert resp.status_code == 200, "本项目用 body.code 表达权限错误"
        assert resp.json()["code"] == 403
        assert resp.json()["message"] == "无权限访问"

    @pytest.mark.parametrize("method,url,payload", ADMIN_CALLS)
    def test_anonymous_denied_on_admin_endpoints(
        self, client, method, url, payload
    ):
        resp = client.request(method, url, json=payload)
        assert resp.status_code == 401

    def test_admin_can_list_users(self, client, make_user, auth_headers):
        admin = make_user(username="boss", role="admin")
        make_user(username="stu")
        resp = client.get(USER_LIST, headers=auth_headers(admin))
        assert resp.json()["code"] == 200
        usernames = {item["username"] for item in resp.json()["data"]["list"]}
        assert {"boss", "stu"} <= usernames

    def test_student_cannot_promote_self_via_profile_update(
        self, client, db, make_user, auth_headers
    ):
        """PUT /me 的请求体虽然能塞 role，但服务端必须忽略它"""
        student = make_user(username="stu", role="student")
        resp = client.put(
            ME,
            headers=auth_headers(student),
            json={"name": "改名了", "role": "admin", "status": 1},
        )
        assert resp.json()["code"] == 200

        _fresh(db)
        after = db.query(User).filter(User.username == "stu").first()
        assert after.name == "改名了", "普通字段应该能改"
        assert after.role == "student", "role 必须被忽略，否则就是提权漏洞"
