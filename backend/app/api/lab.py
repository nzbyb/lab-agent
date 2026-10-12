from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.common.response import Response
from app.models.lab import Lab
from app.dependencies.auth import get_current_admin, get_current_user
from app.schemas.lab import (
    LabUpdateRequest,
    LabCreateRequest,
)
from app.services import kb_service, lab_service
from app.database import get_db

router = APIRouter(prefix="/lab", tags=["实验室信息接口"])


def _refresh_kb_doc() -> None:
    """实验室增删改之后，把知识库里的 开放时间.md 按数据库重画一遍。

    只写文件、不 embed：索引的重建落在下一次 AI 检索那一侧（kb_service 按
    文件指纹判断），所以"保存实验室"这个请求既不依赖向量库能不能用，
    也不会被 bge 模型在 CPU 上几秒钟的加载卡住。函数内部自己吞异常——
    实验室的改动已经提交成功了，不该因为文档没跟上就回 500。

    放在路由层而不是 lab_service 里：渲染文档要问 lab_service.resolve_open_hours
    （"哪天用哪套时段"的唯一判断点），kb_service 已经依赖它了，反过来再依赖
    就成了环。
    """
    kb_service.rebuild_open_hours_doc()


@router.get("/list")
def get_lab_list(
    page: int = Query(1, ge=1),
    # 上界不能省：page_size 会直接进 LIMIT，传个几百万就是一次全表读。
    # 100 是前端分页器实际会用到的最大值（设备页一次拉全部实验室）。
    page_size: int = Query(10, ge=1, le=100),
    keywords: str | None = None,
    status: int | None = None,
    current_user: Lab = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    res = lab_service.get_lab_page_list(db, page, page_size, keywords, status)
    return Response.success(data=res)


@router.get("/{lab_id}")
def get_lab(
    lab_id: int,
    current_user: Lab = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    res = lab_service.get_lab(db, lab_id)
    return Response.success(data=res)


@router.post("")
def create_lab(
    data: LabCreateRequest,
    current_user: Lab = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    res = lab_service.create_lab(db, data)
    _refresh_kb_doc()
    return Response.success(data=res)


@router.put("/{lab_id}")
def update_lab(
    lab_id: int,
    data: LabUpdateRequest,
    current_user: Lab = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    res = lab_service.update_lab(db, lab_id, data)
    _refresh_kb_doc()
    return Response.success(data=res)


@router.delete("/{lab_id}")
def delete_lab(
    lab_id: int,
    current_user: Lab = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    lab_service.delete_lab(db, lab_id)
    _refresh_kb_doc()
    return Response.success()
