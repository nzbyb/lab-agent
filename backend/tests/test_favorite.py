"""收藏与最近浏览。

两条接口都做成幂等的：连点两下心形、两个标签页同时操作，都只该留下一行。
"""

from app.models.favorite import Favorite, LabView

FAVORITE = "/api/favorite"


def _fresh(db):
    db.rollback()


class TestFavorites:
    def test_add_and_list(self, client, db, make_user, make_lab, auth_headers):
        user, lab = make_user(), make_lab(name="计算机实验室")

        assert (
            client.post(f"{FAVORITE}/{lab.id}", headers=auth_headers(user)).json()[
                "code"
            ]
            == 200
        )

        ids = client.get(f"{FAVORITE}/ids", headers=auth_headers(user)).json()
        assert ids["data"] == [lab.id]

        items = client.get(f"{FAVORITE}/list", headers=auth_headers(user)).json()
        assert [item["name"] for item in items["data"]] == ["计算机实验室"]
        # 列表项跟实验室列表是同一个 LabResponse，今日时段也应该带上
        assert "today_open_time" in items["data"][0]

    def test_add_is_idempotent(self, client, db, make_user, make_lab, auth_headers):
        user, lab = make_user(), make_lab()

        for _ in range(3):
            assert (
                client.post(
                    f"{FAVORITE}/{lab.id}", headers=auth_headers(user)
                ).json()["code"]
                == 200
            )

        _fresh(db)
        assert db.query(Favorite).filter_by(user_id=user.id, lab_id=lab.id).count() == 1

    def test_remove_is_idempotent(self, client, make_user, make_lab, auth_headers):
        user, lab = make_user(), make_lab()
        client.post(f"{FAVORITE}/{lab.id}", headers=auth_headers(user))

        for _ in range(2):
            assert (
                client.delete(
                    f"{FAVORITE}/{lab.id}", headers=auth_headers(user)
                ).json()["code"]
                == 200
            )
        assert client.get(f"{FAVORITE}/ids", headers=auth_headers(user)).json()[
            "data"
        ] == []

    def test_favorites_are_per_user(
        self, client, db, make_user, make_lab, auth_headers
    ):
        first, second = make_user(username="first"), make_user(username="second")
        lab = make_lab()

        client.post(f"{FAVORITE}/{lab.id}", headers=auth_headers(first))
        assert client.get(f"{FAVORITE}/ids", headers=auth_headers(second)).json()[
            "data"
        ] == []

    def test_unknown_lab_is_rejected(self, client, make_user, auth_headers):
        user = make_user()
        body = client.post(f"{FAVORITE}/999999", headers=auth_headers(user)).json()
        assert body["code"] == 400
        assert body["message"] == "实验室不存在"

    def test_anonymous_is_rejected(self, client):
        assert client.get(f"{FAVORITE}/ids").status_code == 401


class TestRecentViews:
    def test_view_is_recorded_once_and_refreshes_time(
        self, client, db, make_user, make_lab, auth_headers
    ):
        user, lab = make_user(), make_lab()

        for _ in range(2):
            assert (
                client.post(
                    f"{FAVORITE}/{lab.id}/view", headers=auth_headers(user)
                ).json()["code"]
                == 200
            )

        _fresh(db)
        assert db.query(LabView).filter_by(user_id=user.id, lab_id=lab.id).count() == 1

    def test_recent_views_are_newest_first(
        self, client, db, make_user, make_lab, auth_headers
    ):
        user = make_user()
        first, second = make_lab(name="第一间"), make_lab(name="第二间")

        client.post(f"{FAVORITE}/{first.id}/view", headers=auth_headers(user))
        client.post(f"{FAVORITE}/{second.id}/view", headers=auth_headers(user))

        body = client.get(f"{FAVORITE}/recent", headers=auth_headers(user)).json()
        assert [item["name"] for item in body["data"]] == ["第二间", "第一间"]

    def test_reviewing_moves_a_lab_back_to_the_top(
        self, client, db, make_user, make_lab, auth_headers
    ):
        user = make_user()
        first, second = make_lab(name="第一间"), make_lab(name="第二间")

        client.post(f"{FAVORITE}/{first.id}/view", headers=auth_headers(user))
        client.post(f"{FAVORITE}/{second.id}/view", headers=auth_headers(user))
        # 再看一眼第一间：它应该回到最前面
        client.post(f"{FAVORITE}/{first.id}/view", headers=auth_headers(user))

        body = client.get(f"{FAVORITE}/recent", headers=auth_headers(user)).json()
        assert [item["name"] for item in body["data"]] == ["第一间", "第二间"]

    def test_recent_views_respect_limit(
        self, client, db, make_user, make_lab, auth_headers
    ):
        user = make_user()
        for index in range(3):
            lab = make_lab(name=f"实验室{index}")
            client.post(f"{FAVORITE}/{lab.id}/view", headers=auth_headers(user))

        body = client.get(
            f"{FAVORITE}/recent", headers=auth_headers(user), params={"limit": 2}
        ).json()
        assert len(body["data"]) == 2

    def test_viewing_unknown_lab_is_rejected(self, client, make_user, auth_headers):
        user = make_user()
        body = client.post(f"{FAVORITE}/999999/view", headers=auth_headers(user)).json()
        assert body["code"] == 400
