from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.common.response import Response
from app.models.lab import Lab
from app.dependencies.auth import get_current_admin, get_current_user
from app.schemas.lab import (
    LabUpdateRequest,
    LabCreateRequest,
)
from app.services import lab_service
from app.database import get_db

router = APIRouter(prefix="/lab", tags=["实验室信息接口"])


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
    return Response.success(data=res)


@router.put("/{lab_id}")
def update_lab(
    lab_id: int,
    data: LabUpdateRequest,
    current_user: Lab = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    res = lab_service.update_lab(db, lab_id, data)
    return Response.success(data=res)


@router.delete("/{lab_id}")
def delete_lab(
    lab_id: int,
    current_user: Lab = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    lab_service.delete_lab(db, lab_id)
    return Response.success()
