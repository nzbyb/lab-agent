from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.services import statistics_service

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
