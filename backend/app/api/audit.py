from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_admin
from app.models.user import User
from app.services import audit_service

router = APIRouter(prefix="/audit", tags=["审计日志"])


@router.get("/list")
def get_audit_log_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None, description="login / operation"),
    username: str | None = None,
    action: str | None = Query(None, description="动作代码前缀, 如 login / lab"),
    start_date: str | None = Query(None, description="YYYY-MM-DD"),
    end_date: str | None = Query(None, description="YYYY-MM-DD"),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    res = audit_service.get_log_page_list(
        db,
        page=page,
        page_size=page_size,
        category=category,
        username=username,
        action=action,
        start_date=start_date,
        end_date=end_date,
    )
    return Response.success(data=res)
