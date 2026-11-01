from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

_TITLE_MAX = 100
_CONTENT_MAX = 5000


class AnnouncementCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=_TITLE_MAX)
    content: str = Field(min_length=1, max_length=_CONTENT_MAX)
    pinned: bool = False
    # 默认直接发布；想先存草稿就传 0
    status: int = Field(default=1, ge=0, le=1)


class AnnouncementUpdateRequest(BaseModel):
    """部分更新：只传要改的字段。

    不传 pinned 时不能把它当成 False——那样每次改标题都会顺手把置顶取消掉。
    """

    title: str | None = Field(default=None, min_length=1, max_length=_TITLE_MAX)
    content: str | None = Field(default=None, min_length=1, max_length=_CONTENT_MAX)
    pinned: bool | None = None
    status: int | None = Field(default=None, ge=0, le=1)


class AnnouncementResponse(BaseModel):
    id: int
    title: str
    content: str
    pinned: bool
    status: int
    publisher_id: int | None = None
    publisher_name: str | None = None
    create_time: datetime
    update_time: datetime

    model_config = ConfigDict(from_attributes=True)
