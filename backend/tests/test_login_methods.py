"""手机号+密码、邮箱验证码登录、邮箱验证码注册。

SMTP 一律被替换成"把验证码记下来"，测试绝不连真实邮箱。
"""

from datetime import datetime, timedelta

import pytest

from app.common.exceptions import BusinessException
from app.config import settings
from app.models.user import User
from app.models.verification import VerificationCode
from app.services import verification_service
from app.utils import mailer

DEFAULT_PASSWORD = "pw123456"
PHONE_LOGIN = "/api/auth/login/phone"
SEND_CODE = "/api/auth/email-code"
EMAIL_LOGIN = "/api/auth/login/email-code"
REGISTER = "/api/auth/register"
REGISTER_CODE = "/api/auth/register/email-code"
ME = "/api/user/me"
USER_COLLECTION = "/api/user"


@pytest.fixture
def sent_codes(monkeypatch):
    codes = {}

    def fake_send(email, code):
        codes[email] = code

    # 登录和注册各自走一个函数，测试里都得换成"记下来"。
    monkeypatch.setattr(mailer, "send_login_code", fake_send)
    monkeypatch.setattr(mailer, "send_register_code", fake_send)
    return codes


def _send_code(client, email):
    return client.post(SEND_CODE, json={"email": email}).json()


def _send_register_code(client, email):
    return client.post(REGISTER_CODE, json={"email": email}).json()


class TestPhoneLogin:
    def test_phone_login_success(self, client, make_user):
        make_user(username="phoneuser", phone="13800000001")
        body = client.post(
            PHONE_LOGIN,
            json={"phone": "13800000001", "password": DEFAULT_PASSWORD},
        ).json()
        assert body["code"] == 200
        assert body["data"]["token"]
        assert body["data"]["user"]["username"] == "phoneuser"

    def test_phone_input_is_normalized(self, client, make_user):
        make_user(username="phoneuser", phone="13800000001")
        body = client.post(
            PHONE_LOGIN,
            json={"phone": "138-0000-0001", "password": DEFAULT_PASSWORD},
        ).json()
        assert body["code"] == 200

    def test_wrong_password_and_unknown_phone_look_the_same(self, client, make_user):
        make_user(username="phoneuser", phone="13800000001")
        wrong = client.post(
            PHONE_LOGIN,
            json={"phone": "13800000001", "password": "wrong"},
        ).json()
        unknown = client.post(
            PHONE_LOGIN,
            json={"phone": "13900000002", "password": "wrong"},
        ).json()
        assert wrong["code"] == unknown["code"] == 400
        assert wrong["message"] == unknown["message"] == "手机号或密码错误"

    def test_disabled_account_rejected(self, client, make_user):
        make_user(username="frozen", phone="13800000001", status=0)
        body = client.post(
            PHONE_LOGIN,
            json={"phone": "13800000001", "password": DEFAULT_PASSWORD},
        ).json()
        assert body["code"] == 400
        assert body["message"] == "账号被禁用"

    def test_invalid_phone_format(self, client):
        body = client.post(
            PHONE_LOGIN, json={"phone": "12345", "password": DEFAULT_PASSWORD}
        ).json()
        assert body["code"] == 400
        assert body["message"] == "手机号格式不正确"


class TestEmailCode:
    def test_send_code_to_bound_email(self, client, make_user, sent_codes):
        make_user(username="mailuser", email="mailuser@qq.com")
        body = _send_code(client, "MailUser@QQ.com")
        assert body["code"] == 200
        assert body["data"]["cooldown"] == 60
        assert body["data"]["expires_in"] == 300
        assert sent_codes["mailuser@qq.com"]

    def test_send_code_to_unbound_email(self, client, sent_codes):
        body = _send_code(client, "nobody@qq.com")
        assert body["code"] == 400
        assert body["message"] == "该邮箱未绑定账号"
        assert sent_codes == {}

    def test_send_code_cooldown(self, client, make_user, sent_codes):
        make_user(username="mailuser", email="mailuser@qq.com")
        assert _send_code(client, "mailuser@qq.com")["code"] == 200
        second = _send_code(client, "mailuser@qq.com")
        assert second["code"] == 429
        assert "秒后再获取" in second["message"]

    def test_email_code_login_success(self, client, make_user, sent_codes):
        make_user(username="mailuser", email="mailuser@qq.com")
        assert _send_code(client, "mailuser@qq.com")["code"] == 200

        body = client.post(
            EMAIL_LOGIN,
            json={"email": "mailuser@qq.com", "code": sent_codes["mailuser@qq.com"]},
        ).json()
        assert body["code"] == 200, body
        assert body["data"]["token"]
        assert body["data"]["user"]["username"] == "mailuser"

    def test_code_is_one_time(self, client, make_user, sent_codes):
        make_user(username="mailuser", email="mailuser@qq.com")
        assert _send_code(client, "mailuser@qq.com")["code"] == 200
        code = sent_codes["mailuser@qq.com"]

        first = client.post(
            EMAIL_LOGIN, json={"email": "mailuser@qq.com", "code": code}
        ).json()
        assert first["code"] == 200
        second = client.post(
            EMAIL_LOGIN, json={"email": "mailuser@qq.com", "code": code}
        ).json()
        assert second["code"] == 400
        assert second["message"] == "验证码已失效，请重新获取"

    def test_wrong_code_rejected(self, client, make_user, sent_codes):
        make_user(username="mailuser", email="mailuser@qq.com")
        assert _send_code(client, "mailuser@qq.com")["code"] == 200
        body = client.post(
            EMAIL_LOGIN, json={"email": "mailuser@qq.com", "code": "000000"}
        ).json()
        assert body["code"] == 400
        assert body["message"] == "验证码不正确，请检查后重试"

    def test_expired_code_rejected(self, client, db, make_user, sent_codes):
        make_user(username="mailuser", email="mailuser@qq.com")
        assert _send_code(client, "mailuser@qq.com")["code"] == 200
        code = sent_codes["mailuser@qq.com"]

        # TestClient 用的是另一条连接；当前会话不结束事务就看不到它刚提交的行
        # （MySQL 默认 REPEATABLE READ）。
        db.rollback()
        record = (
            db.query(VerificationCode)
            .filter(VerificationCode.email == "mailuser@qq.com")
            .one()
        )
        record.expires_at = datetime.now() - timedelta(minutes=1)
        db.commit()

        body = client.post(
            EMAIL_LOGIN, json={"email": "mailuser@qq.com", "code": code}
        ).json()
        assert body["code"] == 400
        assert body["message"] == "验证码已过期，请重新获取"

    def test_disabled_account_after_code_sent(self, client, db, make_user, sent_codes):
        user = make_user(username="mailuser", email="mailuser@qq.com")
        assert _send_code(client, "mailuser@qq.com")["code"] == 200
        code = sent_codes["mailuser@qq.com"]

        user.status = 0
        db.commit()

        body = client.post(
            EMAIL_LOGIN, json={"email": "mailuser@qq.com", "code": code}
        ).json()
        assert body["code"] == 400
        assert body["message"] == "账号被禁用"

    def test_wrong_code_attempts_are_limited(self, db, make_user, sent_codes, monkeypatch):
        """直接测服务层：走 HTTP 会先撞上「IP + 邮箱 5 次/分钟」那条限流，
        分不清到底是被哪一层拦下的。"""
        monkeypatch.setattr(settings, "EMAIL_CODE_MAX_ATTEMPTS", 3)
        make_user(username="mailuser", email="mailuser@qq.com")
        verification_service.send_login_code(db, "mailuser@qq.com")
        correct = sent_codes["mailuser@qq.com"]

        for _ in range(2):
            with pytest.raises(BusinessException) as exc:
                verification_service.consume_login_code(
                    db, "mailuser@qq.com", "000000"
                )
            assert exc.value.message == "验证码不正确，请检查后重试"

        # 第 3 次错：达到上限，这条验证码直接作废
        with pytest.raises(BusinessException) as exc:
            verification_service.consume_login_code(db, "mailuser@qq.com", "000000")
        assert exc.value.code == 429
        assert "错误次数过多" in exc.value.message

        # 正确码也不能再用
        with pytest.raises(BusinessException) as exc:
            verification_service.consume_login_code(db, "mailuser@qq.com", correct)
        assert exc.value.message == "验证码已失效，请重新获取"


class TestEmailRegistration:
    def test_send_code_to_new_email(self, client, sent_codes):
        body = _send_register_code(client, "NewUser@QQ.com")
        assert body["code"] == 200
        assert body["data"]["cooldown"] == 60
        assert body["data"]["expires_in"] == 300
        assert sent_codes["newuser@qq.com"]

    def test_send_code_to_bound_email_rejected(self, client, make_user, sent_codes):
        make_user(username="taken", email="taken@qq.com")
        body = _send_register_code(client, "taken@qq.com")
        assert body["code"] == 400
        assert body["message"] == "该邮箱已被注册"
        assert sent_codes == {}

    def test_register_with_email_code(self, client, db, sent_codes):
        assert _send_register_code(client, "newbie@qq.com")["code"] == 200
        code = sent_codes["newbie@qq.com"]

        body = client.post(
            REGISTER,
            json={
                "username": "newbie",
                "password": DEFAULT_PASSWORD,
                "email": "NewBie@QQ.com",
                "code": code,
            },
        ).json()
        assert body["code"] == 200, body

        db.rollback()
        user = db.query(User).filter(User.username == "newbie").one()
        assert user.email == "newbie@qq.com"

    def test_register_without_code_rejected(self, client, db):
        body = client.post(
            REGISTER,
            json={
                "username": "no_code",
                "password": DEFAULT_PASSWORD,
                "email": "no_code@qq.com",
            },
        ).json()
        assert body["code"] == 400
        assert body["message"] == "请输入邮箱验证码"

        db.rollback()
        assert db.query(User).filter(User.username == "no_code").first() is None

    def test_register_with_wrong_code_rejected(self, client, db, sent_codes):
        assert _send_register_code(client, "wrong@qq.com")["code"] == 200
        correct = sent_codes["wrong@qq.com"]
        wrong = "000000" if correct != "000000" else "111111"

        body = client.post(
            REGISTER,
            json={
                "username": "wrong_code",
                "password": DEFAULT_PASSWORD,
                "email": "wrong@qq.com",
                "code": wrong,
            },
        ).json()
        assert body["code"] == 400
        assert body["message"] == "验证码不正确，请检查后重试"

        db.rollback()
        assert db.query(User).filter(User.username == "wrong_code").first() is None

    def test_register_code_is_one_time(self, client, db, sent_codes):
        assert _send_register_code(client, "once@qq.com")["code"] == 200
        code = sent_codes["once@qq.com"]

        db.rollback()
        assert (
            verification_service.consume_register_code(db, "once@qq.com", code)
            == "once@qq.com"
        )
        with pytest.raises(BusinessException) as exc:
            verification_service.consume_register_code(db, "once@qq.com", code)
        assert exc.value.message == "验证码已失效，请重新获取"

    def test_login_code_cannot_be_used_for_register(
        self, client, db, make_user, sent_codes
    ):
        """登录码和注册码是两个 scene，不能互相顶替。"""
        make_user(username="mailuser", email="mailuser@qq.com")
        assert _send_code(client, "mailuser@qq.com")["code"] == 200
        code = sent_codes["mailuser@qq.com"]

        db.rollback()
        with pytest.raises(BusinessException) as exc:
            verification_service.consume_register_code(
                db, "mailuser@qq.com", code
            )
        assert exc.value.message == "验证码已失效，请重新获取"

    def test_register_without_email_still_works(self, client, db):
        """兼容旧客户端和初始化脚本：不传邮箱仍按账号+密码注册。"""
        body = client.post(
            REGISTER,
            json={"username": "legacy", "password": DEFAULT_PASSWORD},
        ).json()
        assert body["code"] == 200

        db.rollback()
        user = db.query(User).filter(User.username == "legacy").one()
        assert user.email is None


class TestContactUniqueness:
    def test_profile_cannot_bind_someone_elses_email(
        self, client, make_user, auth_headers
    ):
        make_user(username="first", email="taken@qq.com")
        second = make_user(username="second")
        body = client.put(
            ME,
            headers=auth_headers(second),
            json={"email": "taken@qq.com"},
        ).json()
        assert body["code"] == 400
        assert body["message"] == "邮箱已被其他账号绑定"

    def test_profile_cannot_bind_someone_elses_phone(
        self, client, make_user, auth_headers
    ):
        make_user(username="first", phone="13800000001")
        second = make_user(username="second")
        body = client.put(
            ME,
            headers=auth_headers(second),
            json={"phone": "13800000001"},
        ).json()
        assert body["code"] == 400
        assert body["message"] == "手机号已被其他账号绑定"

    def test_admin_create_rejects_duplicate_email(
        self, client, make_user, auth_headers
    ):
        admin = make_user(username="boss", role="admin")
        make_user(username="first", email="taken@qq.com")
        body = client.post(
            USER_COLLECTION,
            headers=auth_headers(admin),
            json={
                "username": "newbie",
                "password": "pw123456",
                "name": "新用户",
                "email": "taken@qq.com",
            },
        ).json()
        assert body["code"] == 400
        assert body["message"] == "邮箱已被其他账号绑定"

    def test_empty_contact_fields_become_null(self, client, db, make_user, auth_headers):
        """前端清空输入框发的是空串；空串不能占住唯一索引，否则第二个
        用户就再也清不掉自己的邮箱了。"""
        first = make_user(username="first", email="first@qq.com")
        second = make_user(username="second", email="second@qq.com")

        assert (
            client.put(
                ME, headers=auth_headers(first), json={"email": ""}
            ).json()["code"]
            == 200
        )
        assert (
            client.put(
                ME, headers=auth_headers(second), json={"email": ""}
            ).json()["code"]
            == 200
        )

        db.rollback()
        fresh = db.query(type(first)).filter_by(username="first").one()
        assert fresh.email is None
