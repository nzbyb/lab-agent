from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    id: int
    category: str
    action: str
    user_id: int | None = None
    username: str | None = None
    target_type: str | None = None
    target_id: int | None = None
    detail: str | None = None
    ip: str | None = None
    create_time: datetime

    model_config = ConfigDict(from_attributes=True)
