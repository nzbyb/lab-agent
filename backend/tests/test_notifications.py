"""站内消息：审核 / 取消时给本人留一条，接口只能看自己的。

邮件是副路径，用例里只直接调 `_send_email_safely` 验证内容，
不走后台线程——线程什么时候跑完没法断言，测试会 flaky。
"""

from datetime import datetime, timedelta

from app.models.notification import Notification
from app.models.reservation import Reservation
from app.services import notification_service, reservation_service

# 用"明天"而不是写死日期：create_reservation 拒绝过去的日期，
# 写死的日期过一段时间就会让整组用例红。需要"过去"的用例自己造数据。
DAY = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
DAY2 = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
DAY3 = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")


def _create(db, user, request):
    reservation_service.create_reservation(db, user, request)
    return db.query(Reservation).order_by(Reservation.id.desc()).first()


def _latest(db, user_id):
    db.expire_all()
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(Notification.id.desc())
        .first()
    )


class TestCreateOnReservationEvents:
    def test_approved_creates_message(self, db, make_user, make_lab, booking):
        admin = make_user(username="admin", role="admin")
        user = make_user(username="stu")
        lab = make_lab()
        item = _create(
            db,
            user,
            booking(lab.id, date=DAY, start_time="09:00", end_time="10:00"),
        )

        reservation_service.audit_reservation(db, item.id, 1)

        message = _latest(db, user.id)
        assert message is not None
        assert message.type == notification_service.TYPE_APPROVED
        assert message.title == "预约已通过"
        assert message.reservation_id == item.id
        assert message.is_read is False
        assert lab.name in message.content
        assert "09:00-10:00" in message.content
        # 管理员自己不该收到这条消息
        assert _latest(db, admin.id) is None

    def test_rejected_creates_message(self, db, make_user, make_lab, booking):
        user = make_user(username="stu")
        lab = make_lab()
        item = _create(
            db,
            user,
            booking(lab.id, date=DAY, start_time="09:00", end_time="10:00"),
        )

        reservation_service.audit_reservation(db, item.id, 2)

        message = _latest(db, user.id)
        assert message.type == notification_service.TYPE_REJECTED
        assert message.title == "预约被拒绝"
        assert "未通过审核" in message.content

    def test_force_cancel_includes_reason(
        self, db, make_user, make_lab, booking
    ):
        user = make_user(username="stu")
        lab = make_lab()
        item = _create(
            db,
            user,
            booking(lab.id, date=DAY, start_time="09:00", end_time="10:00"),
        )
        reservation_service.audit_reservation(db, item.id, 1)

        reservation_service.force_cancel_reservation(db, item.id, "设备临时故障")

        message = _latest(db, user.id)
        assert message.type == notification_service.TYPE_FORCE_CANCELED
        assert message.title == "预约已被取消"
        assert "设备临时故障" in message.content

    def test_auto_cancel_creates_message(
        self, db, make_user, make_lab
    ):
        user = make_user(username="stu")
        lab = make_lab()
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        item = Reservation(
            user_id=user.id,
            lab_id=lab.id,
            date=yesterday,
            start_time="09:00",
            end_time="10:00",
            status=0,
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        reservation_service.expire_pending_reservations()

        # expire_pending_reservations 用的是另一个 Session。本用例的 Session
        # 在 refresh 时已经开了一个 REPEATABLE READ 事务，不先结束它，
        # 后面查到的仍是旧快照（status 还是 0）。
        db.rollback()
        fresh = db.query(Reservation).filter(Reservation.id == item.id).one()
        assert fresh.status == 3
        assert fresh.cancel_reason == reservation_service.AUTO_CANCEL_REASON

        message = _latest(db, user.id)
        assert message.type == notification_service.TYPE_AUTO_CANCELED
        assert message.title == "预约已自动取消"
        # 消息正文是给人读的，不要求逐字等于 cancel_reason 那句；
        # 只要说清"超时未审核"和"系统自动取消"即可。
        assert "超时未审核" in message.content
        assert "系统自动取消" in message.content


class TestNotificationApi:
    def _seed(self, db, make_user, make_lab, booking):
        user = make_user(username="stu")
        other = make_user(username="other")
        lab = make_lab()
        for day in (DAY, DAY2):
            item = _create(
                db,
                user,
                booking(lab.id, date=day, start_time="09:00", end_time="10:00"),
            )
            reservation_service.audit_reservation(db, item.id, 1)
        # 另一个人的消息，用来验证"只能看自己的"
        other_item = _create(
            db,
            other,
            booking(lab.id, date=DAY3, start_time="09:00", end_time="10:00"),
        )
        reservation_service.audit_reservation(db, other_item.id, 1)
        return user, other

    def test_requires_login(self, client):
        assert client.get("/api/notification/list").status_code == 401

    def test_list_only_returns_own(
        self, client, db, make_user, make_lab, booking, auth_headers
    ):
        user, _other = self._seed(db, make_user, make_lab, booking)

        body = client.get(
            "/api/notification/list", headers=auth_headers(user)
        ).json()
        assert body["code"] == 200
        assert body["data"]["total"] == 2
        assert {item["type"] for item in body["data"]["list"]} == {
            notification_service.TYPE_APPROVED
        }

    def test_unread_count_and_filters(
        self, client, db, make_user, make_lab, booking, auth_headers
    ):
        user, _other = self._seed(db, make_user, make_lab, booking)
        headers = auth_headers(user)

        count = client.get("/api/notification/unread-count", headers=headers).json()
        assert count["data"]["count"] == 2

        first_id = client.get(
            "/api/notification/list", headers=headers
        ).json()["data"]["list"][0]["id"]
        assert (
            client.put(f"/api/notification/{first_id}/read", headers=headers).json()[
                "code"
            ]
            == 200
        )
        assert (
            client.get("/api/notification/unread-count", headers=headers).json()[
                "data"
            ]["count"]
            == 1
        )

        unread = client.get(
            "/api/notification/list",
            params={"unread_only": True},
            headers=headers,
        ).json()["data"]
        assert unread["total"] == 1
        assert unread["list"][0]["id"] != first_id

        read_all = client.put("/api/notification/read-all", headers=headers).json()
        assert read_all["data"]["count"] == 1
        assert (
            client.get("/api/notification/unread-count", headers=headers).json()[
                "data"
            ]["count"]
            == 0
        )

    def test_cannot_read_other_users_message(
        self, client, db, make_user, make_lab, booking, auth_headers
    ):
        user, other = self._seed(db, make_user, make_lab, booking)
        other_message = (
            db.query(Notification)
            .filter(Notification.user_id == other.id)
            .one()
        )

        # 用普通用户去读别人的消息，接口只说"不存在"，不泄露它属于谁
        body = client.put(
            f"/api/notification/{other_message.id}/read",
            headers=auth_headers(user),
        ).json()
        assert body["code"] == 400
        assert body["message"] == "消息不存在"

        # 确认没被误标成已读（用 other 自己查未读数）
        count = client.get(
            "/api/notification/unread-count", headers=auth_headers(other)
        ).json()["data"]["count"]
        assert count == 1

    def test_email_content_uses_owner_address(
        self, db, make_user, make_lab, booking, monkeypatch
    ):
        user = make_user(username="stu", email="stu@example.com")
        lab = make_lab(name="物理实验室")
        item = _create(
            db,
            user,
            booking(lab.id, date=DAY, start_time="09:00", end_time="10:00"),
        )
        reservation_service.audit_reservation(db, item.id, 1)
        message = _latest(db, user.id)

        sent = {}

        def fake_send(email, subject, content):
            sent.update(email=email, subject=subject, content=content)
            return True

        monkeypatch.setattr(
            notification_service.mailer, "is_configured", lambda: True
        )
        monkeypatch.setattr(
            notification_service.mailer, "send_notification", fake_send
        )
        notification_service._send_email_safely(message.id)

        assert sent["email"] == "stu@example.com"
        assert sent["subject"] == "预约已通过"
        assert "物理实验室" in sent["content"]
