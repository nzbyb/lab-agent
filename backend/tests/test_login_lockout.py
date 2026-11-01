"""连续密码错误 → 锁定账号。

为什么主要在服务层测：走 HTTP 会先撞上「IP + 账号 5 次/分钟」那条限流，
第 6 次请求是 429，分不清拦人的到底是限流还是锁定。锁定逻辑本身跟限流无关，
是这个账号的持久状态。HTTP 只补两条：锁着的账号连正确密码也要拒绝；
登录成功会把计数清零。
"""

from datetime import datetime, timedelta

import pytest

from app.common.exceptions import BusinessException
from app.schemas.auth import LoginRequest, PasswordResetRequest, PhoneLoginRequest
from app.services import auth_service, verification_service
from app.utils import mailer

DEFAULT_PASSWORD = "pw123456"
NEW_PASSWORD = "pw654321"


def _login(db, username, password=DEFAULT_PASSWORD):
    return auth_service.login(db, LoginRequest(username=username, password=password))


def _fail_login(db, username, times):
    for _ in range(times):
        with pytest.raises(BusinessException) as exc:
            _login(db, username, "wrong-password")
        assert exc.value.message == "账号或密码错误"


class TestLockAfterRepeatedFailures:
    def test_five_failures_lock_the_account(self, db, make_user):
        user = make_user()

        _fail_login(db, user.username, auth_service.MAX_LOGIN_FAILURES)

        db.refresh(user)
        assert user.locked_until is not None
        # 计数在锁上的一刻归零：解锁之后重新给满 5 次机会，
        # 否则解锁后第一次输错就又锁 15 分钟。
        assert user.failed_login_count == 0

        with pytest.raises(BusinessException) as exc:
            _login(db, user.username)
        assert "密码错误次数过多" in exc.value.message

    def test_below_threshold_can_still_log_in(self, db, make_user):
        """4 次还差一次，没到上限不该锁。"""
        user = make_user()
        _fail_login(db, user.username, auth_service.MAX_LOGIN_FAILURES - 1)

        assert _login(db, user.username).token

    def test_success_resets_the_counter(self, db, make_user):
        user = make_user()
        _fail_login(db, user.username, 3)

        _login(db, user.username)
        db.refresh(user)
        assert user.failed_login_count == 0
        assert user.locked_until is None

    def test_error_message_rounds_minutes_up(self, db, make_user):
        """还剩 90 秒要报"2 分钟"。报 1 分钟会让用户在最后一分钟反复失败。"""
        user = make_user()
        user.locked_until = datetime.now() + timedelta(seconds=90)
        db.commit()

        with pytest.raises(BusinessException) as exc:
            _login(db, user.username)
        assert exc.value.message == "密码错误次数过多，请 2 分钟后再试"

    def test_expired_lock_lets_login_through(self, db, make_user):
        user = make_user()
        user.locked_until = datetime.now() - timedelta(minutes=1)
        db.commit()

        assert _login(db, user.username).token

        db.refresh(user)
        assert user.locked_until is None

    def test_phone_login_shares_the_same_counter(self, db, make_user):
        """锁定是账号的，不是登录方式的。换手机号这个入口接着试也没用。"""
        user = make_user(phone="13800000001")
        for _ in range(auth_service.MAX_LOGIN_FAILURES):
            with pytest.raises(BusinessException):
                auth_service.login_by_phone(
                    db,
                    PhoneLoginRequest(phone="13800000001", password="wrong-pass"),
                )

        with pytest.raises(BusinessException) as exc:
            _login(db, user.username)
        assert "密码错误次数过多" in exc.value.message

    def test_email_code_reset_clears_the_lock(self, db, make_user, monkeypatch):
        """邮箱验证码本身就证明了身份，重置完不该再让人等 15 分钟。"""
        sent = {}
        monkeypatch.setattr(
            mailer, "send_reset_code", lambda email, code: sent.update({email: code})
        )
        user = make_user(email="locked@qq.com")
        _fail_login(db, user.username, auth_service.MAX_LOGIN_FAILURES)

        verification_service.send_reset_code(db, "locked@qq.com")
        auth_service.reset_password_with_code(
            db,
            PasswordResetRequest(
                email="locked@qq.com",
                code=sent["locked@qq.com"],
                new_password=NEW_PASSWORD,
            ),
        )

        db.refresh(user)
        assert user.locked_until is None
        assert user.failed_login_count == 0
        assert _login(db, user.username, NEW_PASSWORD).token


class TestLockedAccountOverHttp:
    def test_locked_account_rejects_even_the_correct_password(
        self, client, db, make_user
    ):
        user = make_user(username="locked")
        user.locked_until = datetime.now() + timedelta(minutes=10)
        db.commit()

        body = client.post(
            "/api/auth/login",
            json={"username": "locked", "password": DEFAULT_PASSWORD},
        ).json()
        assert body["code"] == 400
        assert "密码错误次数过多" in body["message"]

    def test_successful_login_clears_the_counter(self, client, db, make_user):
        user = make_user(username="alice")
        for _ in range(2):
            client.post(
                "/api/auth/login",
                json={"username": "alice", "password": "wrong-password"},
            )
        assert (
            client.post(
                "/api/auth/login",
                json={"username": "alice", "password": DEFAULT_PASSWORD},
            ).json()["code"]
            == 200
        )

        # TestClient 走的是另一条连接；不结束事务读不到它刚提交的行
        db.rollback()
        fresh = db.query(type(user)).filter_by(username="alice").one()
        assert fresh.failed_login_count == 0
        assert fresh.locked_until is None
