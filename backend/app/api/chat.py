from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.services import chat_service

router = APIRouter(prefix="/chat", tags=["AI会话历史"])


@router.get("/conversations")
def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """当前用户的历史会话，按最近更新倒序。

    只有本人可见，**管理员也看不到别人的**——这是刻意偏离预约那边惯例的设计，
    详见 chat_service.list_conversations 的说明。
    """
    res = chat_service.list_conversations(db, current_user.id, page, page_size)
    return Response.success(data=res)


@router.get("/conversations/{conversation_id}/messages")
def get_messages(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """某条会话的全部消息。

    查不到或不属于自己时给 200 + data=null，不抛业务错误——前端进页面时会拿
    本地记着的会话来恢复，那时会话来可能已被保留上限删掉，这里抛错会让用户
    什么都没干就看到一条红色提示。理由详见 chat_service.get_messages。
    """
    res = chat_service.get_messages(db, current_user.id, conversation_id)
    return Response.success(data=res)


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除一条会话及其全部消息。"""
    if not chat_service.delete_conversation(db, current_user.id, conversation_id):
        # 删除是用户明确点的操作，失败要说清楚，不能安静地什么都不做
        raise BusinessException(message="会话不存在或无权删除", code=403)
    return Response.success(message="删除成功")
