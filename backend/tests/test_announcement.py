"""公告：发布、草稿隔离、置顶排序。

重点钉住两条：
1. 草稿对学生完全不可见——列表不返回，按 id 也查不出来。
2. 部分更新不会把没传的字段重置掉（尤其 pinned）。
"""

from app.models.audit import AuditLog

COLLECTION = "/api/announcement"
LIST = "/api/announcement/list"
DEFAULT_PASSWORD = "pw123456"


def _create(client, headers, **overrides):
    payload = {"title": "系统维护", "content": "周六 08:00-12:00 停机维护"}
    payload.update(overrides)
    return client.post(COLLECTION, headers=headers, json=payload).json()


class TestPublishAndRead:
    def test_admin_publishes_and_student_reads(
        self, client, make_user, auth_headers
    ):
        admin = make_user(username="boss", role="admin")
        student = make_user(username="stu")

        body = _create(client, auth_headers(admin))
        assert body["code"] == 200, body
        assert body["data"]["publisher_name"] == "boss"

        listed = client.get(LIST, headers=auth_headers(student)).json()
        assert listed["data"]["total"] == 1
        assert listed["data"]["list"][0]["title"] == "系统维护"

    def test_student_cannot_publish(self, client, make_user, auth_headers):
        student = make_user(username="stu")
        assert _create(client, auth_headers(student))["code"] == 403

    def test_anonymous_cannot_read(self, client):
        assert client.get(LIST).status_code == 401

    def test_keyword_matches_title_or_content(
        self, client, make_user, auth_headers
    ):
        admin = make_user(username="boss", role="admin")
        student = make_user(username="stu")
        _create(client, auth_headers(admin), title="奖学金通知", content="见附件")
        _create(client, auth_headers(admin), title="选课通知", content="截止到周五")

        headers = auth_headers(student)
        by_title = client.get(LIST, headers=headers, params={"keyword": "奖学金"}).json()
        assert by_title["data"]["total"] == 1

        by_content = client.get(LIST, headers=headers, params={"keyword": "周五"}).json()
        assert by_content["data"]["total"] == 1
        assert by_content["data"]["list"][0]["title"] == "选课通知"


class TestDrafts:
    def test_draft_is_invisible_to_students(self, client, db, make_user, auth_headers):
        admin = make_user(username="boss", role="admin")
        student = make_user(username="stu")
        draft = _create(client, auth_headers(admin), status=0, title="还没想好")
        assert draft["code"] == 200

        listed = client.get(LIST, headers=auth_headers(student)).json()
        assert listed["data"]["total"] == 0

        # 学生就算手动带上 include_draft 也看不到
        sneaky = client.get(
            LIST, headers=auth_headers(student), params={"include_draft": True}
        ).json()
        assert sneaky["data"]["total"] == 0

        detail = client.get(
            f"{COLLECTION}/{draft['data']['id']}", headers=auth_headers(student)
        ).json()
        assert detail["code"] == 400
        assert detail["message"] == "公告不存在"

    def test_admin_can_see_drafts(self, client, make_user, auth_headers):
        admin = make_user(username="boss", role="admin")
        _create(client, auth_headers(admin), status=0, title="草稿一")

        listed = client.get(
            LIST, headers=auth_headers(admin), params={"include_draft": True}
        ).json()
        assert listed["data"]["total"] == 1


class TestOrdering:
    def test_pinned_comes_first(self, client, make_user, auth_headers):
        admin = make_user(username="boss", role="admin")
        student = make_user(username="stu")
        _create(client, auth_headers(admin), title="普通通知")
        _create(client, auth_headers(admin), title="置顶通知", pinned=True)

        listed = client.get(LIST, headers=auth_headers(student)).json()
        assert [item["title"] for item in listed["data"]["list"]] == [
            "置顶通知",
            "普通通知",
        ]


class TestUpdateAndDelete:
    def test_partial_update_keeps_pinned(self, client, db, make_user, auth_headers):
        """只改标题不能顺手把置顶取消——这是 exclude_unset 存在的理由。"""
        admin = make_user(username="boss", role="admin")
        created = _create(client, auth_headers(admin), title="旧标题", pinned=True)
        announcement_id = created["data"]["id"]

        body = client.put(
            f"{COLLECTION}/{announcement_id}",
            headers=auth_headers(admin),
            json={"title": "新标题"},
        ).json()
        assert body["code"] == 200, body
        assert body["data"]["title"] == "新标题"
        assert body["data"]["pinned"] is True

    def test_blank_title_is_rejected(self, client, make_user, auth_headers):
        admin = make_user(username="boss", role="admin")
        body = _create(client, auth_headers(admin), title="   ")
        assert body["code"] == 400
        assert body["message"] == "标题不能为空"

    def test_student_cannot_update_or_delete(
        self, client, make_user, auth_headers
    ):
        admin = make_user(username="boss", role="admin")
        student = make_user(username="stu")
        announcement_id = _create(client, auth_headers(admin))["data"]["id"]

        assert (
            client.put(
                f"{COLLECTION}/{announcement_id}",
                headers=auth_headers(student),
                json={"title": "篡改"},
            ).json()["code"]
            == 403
        )
        assert (
            client.delete(
                f"{COLLECTION}/{announcement_id}", headers=auth_headers(student)
            ).json()["code"]
            == 403
        )

    def test_delete_removes_it(self, client, make_user, auth_headers):
        admin = make_user(username="boss", role="admin")
        announcement_id = _create(client, auth_headers(admin))["data"]["id"]

        assert (
            client.delete(
                f"{COLLECTION}/{announcement_id}", headers=auth_headers(admin)
            ).json()["code"]
            == 200
        )
        assert (
            client.get(
                f"{COLLECTION}/{announcement_id}", headers=auth_headers(admin)
            ).json()["code"]
            == 400
        )

    def test_admin_actions_are_audited(self, client, db, make_user, auth_headers):
        admin = make_user(username="boss", role="admin")
        _create(client, auth_headers(admin), title="审计我")

        db.rollback()
        log = (
            db.query(AuditLog).filter_by(action="announcement.create").one()
        )
        assert log.user_id == admin.id
        assert "审计我" in log.detail
