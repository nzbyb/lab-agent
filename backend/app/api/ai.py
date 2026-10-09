import json
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from app.common.response import Response
from sqlalchemy.orm import Session
from app.database import get_db

from app.dependencies.auth import get_current_user
from app.limiter import limiter
from app.models.user import User
from app.schemas.ai import ChatMessage, ChatRequest
from app.services import ai_service, agent_service

router = APIRouter(prefix="/ai", tags=["AI相关的API"])


# @router.post("/chat")
# def chat(
#     data: ChatRequest,
#     current_user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     content = agent_service.run_agent(db, current_user, data)
#     return Response.success(data=ChatMessage(role="assistant", content=content))


# 每次对话都要真金白银调一次大模型，而且是流式长连接，单次能占住很久。
# 不限流的话一个脚本就能把额度刷干、把并发连接占满。
# 注意：slowapi 要求在签名里有个名字正好是 request 的参数，别改名。
@router.post("/chat/stream")
@limiter.limit("20/minute")
async def chat_stream(
    request: Request,
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    async def event_gen():
        async for event in agent_service.stream_agent(db, current_user, data):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
