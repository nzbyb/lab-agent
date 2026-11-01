"""预约报表导出（.xlsx）。

不只看"返回 200"：真把文件读回来，核对表头、单元格内容和汇总页。
文件生成失败时最容易出现的假绿，就是只断言了状态码。
"""

from io import BytesIO

from openpyxl import load_workbook

from app.models.audit import AuditLog
from app.models.reservation import Reservation
from app.services import reservation_service

EXPORT = "/api/statistics/export/reservations"
DAY_ONE = "2030-01-01"
DAY_TWO = "2030-01-02"


def _create(
    db, user, booking, lab, date=DAY_ONE, start_time="09:00", end_time="10:00"
):
    reservation_service.create_reservation(
        db, user, booking(lab.id, date=date, start_time=start_time, end_time=end_time)
    )
    return db.query(Reservation).order_by(Reservation.id.desc()).first()


def _sheet(client, headers, **params):
    response = client.get(EXPORT, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return load_workbook(BytesIO(response.content))


class TestExportFile:
    def test_file_contains_the_reservation(
        self, client, db, make_user, make_lab, booking, auth_headers
    ):
        admin = make_user(username="boss", role="admin")
        student = make_user(username="stu", name="张三")
        lab = make_lab(name="计算机实验室")
        _create(db, student, booking, lab)

        workbook = _sheet(client, auth_headers(admin))

        sheet = workbook["预约明细"]
        assert sheet["A1"].value == "预约ID"
        assert sheet["B2"].value == "张三"
        assert sheet["C2"].value == "stu"
        assert sheet["D2"].value == "计算机实验室"
        assert sheet["F2"].value == DAY_ONE
        assert sheet["I2"].value == "待审核"

    def test_summary_sheet_counts_by_status(
        self, client, db, make_user, make_lab, booking, auth_headers
    ):
        admin = make_user(username="boss", role="admin")
        student = make_user(username="stu")
        lab = make_lab()

        pending = _create(db, student, booking, lab)
        approved = _create(
            db, student, booking, lab, start_time="10:00", end_time="11:00"
        )
        reservation_service.audit_reservation(db, approved.id, 1)

        workbook = _sheet(client, auth_headers(admin))
        summary = workbook["汇总"]
        counts = {
            summary.cell(row=row, column=1).value: summary.cell(row=row, column=2).value
            for row in range(2, summary.max_row + 1)
        }
        assert counts["待审核"] == 1
        assert counts["已通过"] == 1
        assert counts["已拒绝"] == 0
        assert counts["合计"] == 2

    def test_content_disposition_has_the_filename(
        self, client, make_user, auth_headers
    ):
        admin = make_user(username="boss", role="admin")
        response = client.get(EXPORT, headers=auth_headers(admin))
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        # 中文文件名走 RFC 5987 的 filename*，否则浏览器会存成乱码
        assert "filename*=UTF-8''" in response.headers["content-disposition"]

    def test_export_is_audited(
        self, client, db, make_user, auth_headers
    ):
        admin = make_user(username="boss", role="admin")
        client.get(EXPORT, headers=auth_headers(admin))

        db.rollback()
        log = db.query(AuditLog).filter_by(action="statistics.export").one()
        assert log.user_id == admin.id


class TestFilters:
    def test_date_range(
        self, client, db, make_user, make_lab, booking, auth_headers
    ):
        admin = make_user(username="boss", role="admin")
        student = make_user(username="stu")
        lab = make_lab()
        _create(db, student, booking, lab, date=DAY_ONE)
        _create(db, student, booking, lab, date=DAY_TWO)

        sheet = _sheet(
            client, auth_headers(admin), date_from=DAY_TWO, date_to=DAY_TWO
        )["预约明细"]
        assert sheet.max_row == 2  # 表头 + 1 行
        assert sheet["F2"].value == DAY_TWO

    def test_status_filter(
        self, client, db, make_user, make_lab, booking, auth_headers
    ):
        admin = make_user(username="boss", role="admin")
        student = make_user(username="stu")
        lab = make_lab()
        _create(db, student, booking, lab)
        approved = _create(
            db, student, booking, lab, start_time="10:00", end_time="11:00"
        )
        reservation_service.audit_reservation(db, approved.id, 1)

        sheet = _sheet(client, auth_headers(admin), status=1)["预约明细"]
        assert sheet.max_row == 2
        assert sheet["I2"].value == "已通过"

    def test_reversed_range_is_rejected(self, client, make_user, auth_headers):
        admin = make_user(username="boss", role="admin")
        body = client.get(
            EXPORT,
            headers=auth_headers(admin),
            params={"date_from": DAY_TWO, "date_to": DAY_ONE},
        ).json()
        assert body["code"] == 400
        assert body["message"] == "开始日期不能晚于结束日期"

    def test_invalid_date_is_rejected(self, client, make_user, auth_headers):
        admin = make_user(username="boss", role="admin")
        body = client.get(
            EXPORT, headers=auth_headers(admin), params={"date_from": "2026-02-30"}
        ).json()
        assert body["code"] == 400
        assert "格式应为 YYYY-MM-DD" in body["message"]


class TestPermission:
    def test_student_is_rejected(self, client, make_user, auth_headers):
        student = make_user(username="stu")
        body = client.get(EXPORT, headers=auth_headers(student)).json()
        assert body["code"] == 403

    def test_anonymous_is_rejected(self, client):
        assert client.get(EXPORT).status_code == 401
