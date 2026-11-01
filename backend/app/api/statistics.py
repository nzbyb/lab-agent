from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_admin, get_current_user
from app.models.user import User
from app.services import audit_service, statistics_service

router = APIRouter(prefix="/statistics", tags=["统计相关接口"])


@router.get("/overview")
def get_statistics_overview(
    # 学生和管理员都能调：首页两个角色都看。实验室/设备总量对学生可见也有先例
    # （/api/lab/list 和 /api/equipment/list 用的就是 get_current_user）。
    # 预约类指标在 service 里按角色分范围，管理员看全库、其余只看自己的。
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    res = statistics_service.get_overview(db, current_user)
    return Response.success(data=res)


@router.get("/admin-workbench")
def get_admin_workbench(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    res = statistics_service.get_admin_workbench(db)
    return Response.success(data=res)


@router.get("/export/reservations")
def export_reservations(
    date_from: str | None = Query(None, description="YYYY-MM-DD，按预约日期筛"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
    status: int | None = Query(None, ge=0, le=3),
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """导出预约明细为 .xlsx。

    这里刻意不套 Response.success 那层壳：文件下载要么是文件本身，
    要么是错误；前端靠 Content-Type 判断拿到的是哪一种。
    """
    content, filename = statistics_service.export_reservations(
        db, date_from=date_from, date_to=date_to, status=status
    )
    audit_service.record(
        category=audit_service.CATEGORY_OPERATION,
        action="statistics.export",
        user=current_user,
        target_type="reservation",
        detail=f"导出预约报表（{date_from or '不限'} ~ {date_to or '不限'}）",
    )
    # 中文文件名必须走 RFC 5987 的 filename*：直接塞进 filename= 会让部分浏览器乱码
    disposition = (
        "attachment; filename=\"reservations.xlsx\"; "
        f"filename*=UTF-8''{quote(filename)}"
    )
    return StreamingResponse(
        BytesIO(content),
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": disposition},
    )
