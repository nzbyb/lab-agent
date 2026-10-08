import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from app.common.response import Response
from sqlalchemy.orm import Session
from app.database import get_db

from app.dependencies.auth import get_current_user
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


@router.post("/chat/stream")
async def chat_stream(
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
