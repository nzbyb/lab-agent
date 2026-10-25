"""退出登录要让服务端的令牌也失效，而不只是清浏览器里的 localStorage。"""

from app.models.user import User

LOGOUT = "/api/auth/logout"
LOGIN = "/api/auth/login"
ME = "/api/user/me"


def test_logout_invalidates_the_current_token(client, db, make_user, auth_headers):
    user = make_user(username="logout_user")
    headers = auth_headers(user)

    # 退出之前：令牌可用
    assert client.get(ME, headers=headers).status_code == 200

    body = client.post(LOGOUT, headers=headers).json()
    assert body["code"] == 200

    # 退出之后：同一枚令牌立刻 401，而不是等到自然过期
    resp = client.get(ME, headers=headers)
    assert resp.status_code == 401
    assert resp.json()["message"] == "登录已失效，请重新登录"

    # 版本号确实 +1 了
    db.rollback()
    assert db.query(User).filter(User.id == user.id).first().token_version == 1


def test_login_again_after_logout_gets_a_working_token(client, db, make_user):
    make_user(username="relogin_user")
    login_body = client.post(
        LOGIN, json={"username": "relogin_user", "password": "pw123456"}
    ).json()
    old_token = login_body["data"]["token"]
    old_headers = {"Authorization": f"Bearer {old_token}"}

    client.post(LOGOUT, headers=old_headers)

    new_body = client.post(
        LOGIN, json={"username": "relogin_user", "password": "pw123456"}
    ).json()
    assert new_body["code"] == 200
    new_headers = {"Authorization": f"Bearer {new_body['data']['token']}"}

    # 新令牌能用，旧令牌仍然作废
    assert client.get(ME, headers=new_headers).status_code == 200
    assert client.get(ME, headers=old_headers).status_code == 401


def test_logout_requires_login(client):
    resp = client.post(LOGOUT)
    assert resp.status_code == 401
