from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    id: int
    type: str
    title: str
    content: str
    reservation_id: int | None = None
    is_read: bool
    create_time: datetime
    read_time: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
