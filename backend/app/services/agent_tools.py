from datetime import datetime
import json

from sqlalchemy.orm import Session
from langchain_core.tools import tool

from app.common.exceptions import BusinessException
from app.models.user import User
from app.schemas.reservation import ReservationCreateRequest
from app.services import kb_service, lab_service, equipment_service, reservation_service


def build_tools(db: Session, current_user: User):

    @tool
    def search_lab_docs(query: str) -> str:
        """查询实验室的资料文档（预约规则、安全规范、开放时间、设备使用说明）。query 是要检索的问题关键词。"""
        try:
            return kb_service.search(query) or "没有检索到相关的资料"
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @tool
    def list_open_labs(keywords: str = "") -> str:
        """查询当前开放中的实验室列表，返回实验室的 id、名称、位置、容量和开放时间。keywords 是实验室名称关键字，可以为空字符串。"""
        try:
            keywords = keywords.strip() or None
            page = lab_service.get_lab_page_list(
                db, page=1, page_size=10, keywords=keywords, status=1
            )

            rows = [
                {
                    "id": item.id,
                    "name": item.name,
                    "location": item.location,
                    "capacity": item.capacity,
                    "open_time": item.open_time,
                    "close_time": item.close_time,
                }
                for item in page.list
            ]
            return json.dumps({"total": page.total, "labs": rows}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @tool
    def list_lab_equipments(lab_id: int, keywords: str = "") -> str:
        """查询某个实验室下的设备列表。lab_id 是实验室 ID（必填），keywords 是设备名称关键字，可以为空字符串。"""
        try:
            keywords = keywords.strip() or None
            page = equipment_service.get_equipment_page_list(
                db, page=1, page_size=10, lab_id=int(lab_id), keywords=keywords
            )
            rows = [
                {
                    "id": item.id,
                    "name": item.name,
                    "lab_id": item.lab_id,
                    "lab_name": item.lab_name,
                    "spec": item.spec,
                    "quantity": item.quantity,
                    "status": item.status,
                }
                for item in page.list
            ]
            return json.dumps(
                {"total": page.total, "equipments": rows}, ensure_ascii=False
            )
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @tool
    def list_lab_free_slots(lab_id: int, date: str, equipment_id: int | None = None) -> str:
        """查询某个实验室（或某台设备）在某一天的空闲时段。lab_id 是实验室 ID（必填），date 格式为 YYYY-MM-DD，查某台设备时再传 equipment_id。用于回答"这天能不能约""几点到几点有空"。"""
        try:
            res = reservation_service.get_free_slots(db, lab_id, date, equipment_id)
            return json.dumps(
                {
                    "lab_id": res.lab_id,
                    "lab_name": res.lab_name,
                    "equipment_id": res.equipment_id,
                    "equipment_name": res.equipment_name,
                    "date": res.date,
                    "open_time": res.open_time,
                    "close_time": res.close_time,
                    "free_slots": [item.model_dump() for item in res.slots],
                    "busy_slots": [item.model_dump() for item in res.busy],
                },
                ensure_ascii=False,
            )
        except BusinessException as exc:
            return json.dumps({"ok": False, "error": exc.message}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @tool
    def create_lab_reservation(
        lab_id: int,
        date: str,
        start_time: str,
        end_time: str,
        equipment_id: int | None = None,
        remark: str | None = None,
    ) -> str:
        """帮用户提交实验室（或设备）的预约。只有在用户明确确认了实验室、日期和时段之后才能调用。date 格式为 YYYY-MM-DD，start_time 和 end_time 格式为 HH:MM。"""
        try:
            data = ReservationCreateRequest(
                lab_id=lab_id,
                equipment_id=equipment_id,
                date=date,
                start_time=start_time,
                end_time=end_time,
                remark=remark,
            )
            reservation_service.create_reservation(db, current_user, data)
            return json.dumps(
                {
                    "ok": True,
                    "message": "预约已提交，请等待管理员审核",
                    "lab_id": lab_id,
                    "equipment_id": equipment_id,
                    "date": date,
                    "start_time": start_time,
                    "end_time": end_time,
                },
                ensure_ascii=False,
            )

        except BusinessException as exc:
            return json.dumps({"ok": False, "error": exc.message}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @tool
    def get_today() -> str:
        """获取今天的日期，格式为 YYYY-MM-DD。用于把"今天""明天"换算成具体的日期。"""
        return datetime.now().strftime("%Y-%m-%d")

    return [
        search_lab_docs,
        list_open_labs,
        list_lab_equipments,
        list_lab_free_slots,
        create_lab_reservation,
        get_today,
    ]
