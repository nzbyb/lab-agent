"""改密码之后，此前签发的令牌必须立刻失效。

这就是 token_version 存在的全部理由：光把密码哈希换掉没用——抓走旧令牌的人照样能
用到过期为止（默认 24 小时）。所以改密码时把 users.token_version +1，而每张令牌里
都带着签发那一刻的版本号，下一个请求在 dependencies/auth.py 里一对就对不上。

顺带补上 `PUT /api/user/password`（本人改密码）和 `PUT /api/user/{id}/password`
（管理员重置他人密码）两条路的用例——在此之前它们一条覆盖都没有。
后者同样要 +1：重置的典型场景就是"号被盗了"，不踢掉旧令牌等于没重置。

注意这里**不需要**额外查一次数据库来比版本号：鉴权本来每个请求就查一次 User，
这个比对是白搭的。这也是选这个方案而不是会话表/Redis 的原因之一。
"""

from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings
from app.models.user import User

LOGIN = "/api/auth/login"
ME = "/api/user/me"
PASSWORD = "/api/user/password"

OLD = "pw123456"
NEW = "newpw123456"


def _fresh(db):
    """结束当前事务，好读到其它连接刚提交的数据（MySQL 默认为 REPEATABLE READ）"""
    db.rollback()


def _change_password(client, headers, old=OLD, new=NEW):
    return client.put(
        PASSWORD, json={"old_password": old, "new_password": new}, headers=headers
    )


class TestPasswordChangeInvalidatesOldTokens:
    def test_old_token_rejected_after_change(self, client, make_user, auth_headers):
        user = make_user(username="alice", password=OLD)
        headers = auth_headers(user)

        # 先证明确实是这把令牌坏了，而不是它本来就不好使
        assert client.get(ME, headers=headers).status_code == 200

        assert _change_password(client, headers).json()["code"] == 200

        resp = client.get(ME, headers=headers)
        assert resp.status_code == 401
        assert resp.json()["message"] == "登录已失效，请重新登录"

    def test_version_is_bumped_in_database(
        self, client, db, make_user, auth_headers
    ):
        user = make_user(username="alice", password=OLD)
        user_id = user.id
        assert user.token_version == 0, "新用户的版本号应当是 0"

        _change_password(client, auth_headers(user))

        _fresh(db)
        reloaded = db.query(User).filter(User.id == user_id).first()
        assert reloaded.token_version == 1

    def test_relogin_with_new_password_works(
        self, client, make_user, auth_headers
    ):
        """改完密码用新密码重新登录，新令牌必须能用——别把人锁在门外"""
        user = make_user(username="alice", password=OLD)
        old_headers = auth_headers(user)

        _change_password(client, old_headers)

        body = client.post(LOGIN, json={"username": "alice", "password": NEW}).json()
        assert body["code"] == 200
        new_headers = {"Authorization": f"Bearer {body['data']['token']}"}

        assert client.get(ME, headers=new_headers).status_code == 200
        # 旧令牌不会因为"又登录了一次"复活
        assert client.get(ME, headers=old_headers).status_code == 401

    def test_old_password_can_no_longer_log_in(self, client, make_user, auth_headers):
        user = make_user(username="alice", password=OLD)
        _change_password(client, auth_headers(user))

        resp = client.post(LOGIN, json={"username": "alice", "password": OLD})
        assert resp.json()["message"] == "账号或密码错误"

    def test_wrong_old_password_does_not_kill_the_token(
        self, client, db, make_user, auth_headers
    ):
        """改密码失败 → 什么都没发生 → 手里的令牌不该被连累"""
        user = make_user(username="alice", password=OLD)
        user_id = user.id
        headers = auth_headers(user)

        resp = _change_password(client, headers, old="definitely-wrong")
        assert resp.json()["message"] == "原密码错误"

        assert client.get(ME, headers=headers).status_code == 200

        _fresh(db)
        assert db.query(User).filter(User.id == user_id).first().token_version == 0

    def test_same_password_rejected_without_bumping(
        self, client, db, make_user, auth_headers
    ):
        """新旧相同会被拦下，同样不该 +1"""
        user = make_user(username="alice", password=OLD)
        user_id = user.id
        headers = auth_headers(user)

        resp = _change_password(client, headers, old=OLD, new=OLD)
        assert resp.json()["message"] == "新密码不能跟原密码相同"

        assert client.get(ME, headers=headers).status_code == 200

        _fresh(db)
        assert db.query(User).filter(User.id == user_id).first().token_version == 0


class TestVersionClaimItself:
    def test_claim_that_does_not_match_is_rejected(self, client, make_user):
        """版本号对不上就拒——这就是"旧令牌失效"的机制本身

        直接造一张 ver 跟库里对不上的令牌，绕开"改密码"这个入口来验机制。
        """
        user = make_user(username="alice", password=OLD)
        ahead = jwt.encode(
            {
                "user_id": user.id,
                "ver": 99,
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )
        resp = client.get(ME, headers={"Authorization": f"Bearer {ahead}"})
        assert resp.status_code == 401


class TestLegacyTokenCompatibility:
    """加 token_version 那一版**之前**签发的令牌里没有 ver 声明。

    校验时按 0 处理，而老库迁移时这一列也一律补 0，两边对得上，所以这些老令牌仍然可用
    ——部署这一版不会把已登录的人全踢下线。

    代价要说在明处：上线**之前**就改过密码、手里还攥着那枚旧令牌的人，这次上线救不了他，
    得等他下次再改密码。想"上线即全清"只能换 JWT_SECRET_KEY，那是全员掉线，不划算。
    """

    @staticmethod
    def _legacy_token(user):
        return jwt.encode(
            {
                "user_id": user.id,
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )

    def test_legacy_token_still_works(self, client, make_user):
        user = make_user(username="alice", password=OLD)
        headers = {"Authorization": f"Bearer {self._legacy_token(user)}"}
        assert client.get(ME, headers=headers).status_code == 200

    def test_legacy_token_dies_at_the_next_password_change(
        self, client, make_user, auth_headers
    ):
        """"兼容"不等于"永远有效"——用户下次改密码时它照样被清掉"""
        user = make_user(username="alice", password=OLD)
        headers = {"Authorization": f"Bearer {self._legacy_token(user)}"}

        _change_password(client, auth_headers(user))

        resp = client.get(ME, headers=headers)
        assert resp.status_code == 401
        assert resp.json()["message"] == "登录已失效，请重新登录"


class TestAdminResetPassword:
    """管理员重置他人密码：PUT /api/user/{user_id}/password

    这条路的典型场景就是"这个人的号可能被盗了"，所以**重置必须连令牌一起清**。
    只换哈希不换版本号的话，盗号者手里那枚令牌照样有效到过期（默认 24 小时），
    真正的主人还以为自己已经把对方踢出去了——那比不做还危险。

    顺带钉住"不要原密码"这件事：请求体里根本没有 old_password 字段，
    管理员本来也不该知道对方的密码。
    """

    @staticmethod
    def _reset(client, headers, user_id, new=NEW):
        return client.put(
            f"/api/user/{user_id}/password",
            json={"new_password": new},
            headers=headers,
        )

    def test_old_token_rejected_after_admin_reset(
        self, client, make_user, auth_headers
    ):
        alice = make_user(username="alice", password=OLD)
        admin = make_user(username="root", role="admin")
        alice_headers = auth_headers(alice)

        # 先证明确实是重置把它弄坏的，而不是这把令牌本来就不行
        assert client.get(ME, headers=alice_headers).status_code == 200

        assert self._reset(client, auth_headers(admin), alice.id).json()["code"] == 200

        resp = client.get(ME, headers=alice_headers)
        assert resp.status_code == 401
        assert resp.json()["message"] == "登录已失效，请重新登录"

    def test_version_bumped_in_database(self, client, db, make_user, auth_headers):
        alice = make_user(username="alice", password=OLD)
        admin = make_user(username="root", role="admin")
        alice_id = alice.id
        assert alice.token_version == 0

        self._reset(client, auth_headers(admin), alice_id)

        _fresh(db)
        assert db.query(User).filter(User.id == alice_id).first().token_version == 1

    def test_new_password_works_and_old_one_does_not(
        self, client, make_user, auth_headers
    ):
        alice = make_user(username="alice", password=OLD)
        admin = make_user(username="root", role="admin")

        self._reset(client, auth_headers(admin), alice.id)

        assert (
            client.post(LOGIN, json={"username": "alice", "password": NEW}).json()["code"]
            == 200
        )
        assert (
            client.post(LOGIN, json={"username": "alice", "password": OLD}).json()[
                "message"
            ]
            == "账号或密码错误"
        )

    def test_admin_own_token_survives(self, client, make_user, auth_headers):
        """重置别人不该把管理员自己牵连下线"""
        alice = make_user(username="alice", password=OLD)
        admin = make_user(username="root", role="admin")
        admin_headers = auth_headers(admin)

        self._reset(client, admin_headers, alice.id)

        assert client.get(ME, headers=admin_headers).status_code == 200

    def test_resetting_self_also_kicks_self_out(self, client, make_user, auth_headers):
        """管理员重置自己的密码，自己也会掉线——这是对的，不是 bug。

        重置的语义就是"换掉密码并作废此前所有令牌"，对谁执行都一样。
        界面上管理员改自己的密码走 /manager/password，那条会主动跳登录页。
        """
        admin = make_user(username="root", role="admin")
        admin_headers = auth_headers(admin)

        self._reset(client, admin_headers, admin.id)

        assert client.get(ME, headers=admin_headers).status_code == 401

    def test_unknown_user_rejected(self, client, make_user, auth_headers):
        admin = make_user(username="root", role="admin")

        resp = self._reset(client, auth_headers(admin), 999999)

        # 业务错误走 HTTP 200 + body.code，别"顺手修正"成 404
        assert resp.status_code == 200
        assert resp.json()["message"] == "用户不存在"
