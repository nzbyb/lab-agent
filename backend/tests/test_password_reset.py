"""忘记密码：邮箱验证码 → 设置新密码。

跟登录/注册共用验证码表，但走独立的 reset 场景：登录码不能拿来重置，
重置码也不能拿去登录。
"""

import pytest

from app.common.exceptions import BusinessException
from app.models.user import User
from app.services import verification_service
from app.utils import mailer

DEFAULT_PASSWORD = "pw123456"
NEW_PASSWORD = "newpw123456"
SEND_RESET_CODE = "/api/auth/password/email-code"
RESET_PASSWORD = "/api/auth/password/reset"
SEND_LOGIN_CODE = "/api/auth/email-code"
LOGIN = "/api/auth/login"
ME = "/api/user/me"


@pytest.fixture
def sent_codes(monkeypatch):
    """三种验证码都替换成"把码记下来"，绝不连真实 SMTP。"""
    codes = {}

    def fake_send(email, code):
        codes[email] = code

    monkeypatch.setattr(mailer, "send_login_code", fake_send)
    monkeypatch.setattr(mailer, "send_register_code", fake_send)
    monkeypatch.setattr(mailer, "send_reset_code", fake_send)
    return codes


def _send(client, email):
    return client.post(SEND_RESET_CODE, json={"email": email}).json()


def _reset(client, email, code, password=NEW_PASSWORD):
    return client.post(
        RESET_PASSWORD,
        json={"email": email, "code": code, "new_password": password},
    ).json()


class TestSendResetCode:
    def test_send_to_bound_email(self, client, make_user, sent_codes):
        make_user(username="stu", email="stu@qq.com")
        body = _send(client, "Stu@QQ.com")
        assert body["code"] == 200
        assert body["data"]["cooldown"] == 60
        # 邮箱统一小写后再发信
        assert sent_codes["stu@qq.com"]

    def test_unbound_email_rejected(self, client, sent_codes):
        body = _send(client, "nobody@qq.com")
        assert body["code"] == 400
        assert body["message"] == "该邮箱未绑定账号"
        assert sent_codes == {}

    def test_disabled_account_rejected(self, client, make_user, sent_codes):
        make_user(username="frozen", email="frozen@qq.com", status=0)
        body = _send(client, "frozen@qq.com")
        assert body["code"] == 400
        assert body["message"] == "账号被禁用"
        assert sent_codes == {}

    def test_cooldown(self, client, make_user, sent_codes):
        make_user(username="stu", email="stu@qq.com")
        assert _send(client, "stu@qq.com")["code"] == 200
        second = _send(client, "stu@qq.com")
        assert second["code"] == 429
        assert "秒后再获取" in second["message"]


class TestResetPassword:
    def test_reset_success_and_old_password_stops_working(
        self, client, db, make_user, sent_codes, auth_headers
    ):
        user = make_user(
            username="stu", password=DEFAULT_PASSWORD, email="stu@qq.com"
        )
        old_headers = auth_headers(user)
        assert _send(client, "stu@qq.com")["code"] == 200

        body = _reset(client, "stu@qq.com", sent_codes["stu@qq.com"])
        assert body["code"] == 200, body

        # 旧密码失效，新密码能登录
        old_login = client.post(
            LOGIN, json={"username": "stu", "password": DEFAULT_PASSWORD}
        ).json()
        assert old_login["code"] == 400
        new_login = client.post(
            LOGIN, json={"username": "stu", "password": NEW_PASSWORD}
        ).json()
        assert new_login["code"] == 200

        # token_version +1：重置之前签出的令牌必须立刻作废
        db.rollback()
        refreshed = db.query(User).filter(User.username == "stu").one()
        assert refreshed.token_version == 1
        resp = client.get(ME, headers=old_headers)
        assert resp.status_code == 401
        assert resp.json()["message"] == "登录已失效，请重新登录"

    def test_wrong_code_rejected(self, client, make_user, sent_codes):
        make_user(username="stu", email="stu@qq.com")
        assert _send(client, "stu@qq.com")["code"] == 200
        correct = sent_codes["stu@qq.com"]
        wrong = "000000" if correct != "000000" else "111111"

        body = _reset(client, "stu@qq.com", wrong)
        assert body["code"] == 400
        assert body["message"] == "验证码不正确，请检查后重试"

        # 码还在，用正确的仍可以重置
        assert _reset(client, "stu@qq.com", correct)["code"] == 200

    def test_code_is_one_time(self, client, db, make_user, sent_codes):
        make_user(username="stu", email="stu@qq.com")
        assert _send(client, "stu@qq.com")["code"] == 200
        code = sent_codes["stu@qq.com"]

        assert _reset(client, "stu@qq.com", code)["code"] == 200
        second = _reset(client, "stu@qq.com", code, password="another123")
        assert second["code"] == 400
        assert second["message"] == "验证码已失效，请重新获取"

    def test_login_code_cannot_reset_password(
        self, client, db, make_user, sent_codes
    ):
        """登录码和找回密码码是两个 scene，不能互相顶替。"""
        make_user(username="stu", email="stu@qq.com")
        assert client.post(
            SEND_LOGIN_CODE, json={"email": "stu@qq.com"}
        ).json()["code"] == 200
        code = sent_codes["stu@qq.com"]

        db.rollback()
        with pytest.raises(BusinessException) as exc:
            verification_service.consume_reset_code(db, "stu@qq.com", code)
        assert exc.value.message == "验证码已失效，请重新获取"

    def test_reset_code_cannot_be_used_to_login(
        self, client, make_user, sent_codes
    ):
        make_user(username="stu", email="stu@qq.com")
        assert _send(client, "stu@qq.com")["code"] == 200
        code = sent_codes["stu@qq.com"]

        body = client.post(
            "/api/auth/login/email-code",
            json={"email": "stu@qq.com", "code": code},
        ).json()
        assert body["code"] == 400
        assert body["message"] == "验证码已失效，请重新获取"

    def test_unbound_email_after_code_sent(self, client, db, make_user, sent_codes):
        """发码后邮箱被解绑：重置那一步要拒绝，不能改到别人的号上。"""
        user = make_user(username="stu", email="stu@qq.com")
        assert _send(client, "stu@qq.com")["code"] == 200
        code = sent_codes["stu@qq.com"]

        user.email = None
        db.commit()

        body = _reset(client, "stu@qq.com", code)
        assert body["code"] == 400
        assert body["message"] == "该邮箱未绑定账号"
