from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.common.response import PageResponse
from app.models.announcement import Announcement
from app.models.user import User
from app.schemas.announcement import (
    AnnouncementCreateRequest,
    AnnouncementResponse,
    AnnouncementUpdateRequest,
)


def get_announcement_page_list(
    db: Session,
    page: int = 1,
    page_size: int = 10,
    include_draft: bool = False,
    keyword: str | None = None,
) -> PageResponse:
    query = db.query(Announcement)
    if not include_draft:
        query = query.filter(Announcement.status == 1)
    if keyword and keyword.strip():
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(Announcement.title.like(like), Announcement.content.like(like))
        )

    total = query.count()
    items = (
        # 置顶在前，同组内新的在前。布尔列在 MySQL 里就是 0/1，可以直接倒序。
        query.order_by(Announcement.pinned.desc(), Announcement.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PageResponse(
        list=[AnnouncementResponse.model_validate(item) for item in items],
        total=total,
    )


def get_announcement(
    db: Session, announcement_id: int, include_draft: bool = False
) -> AnnouncementResponse:
    item = db.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not item:
        raise BusinessException(message="公告不存在")
    if item.status != 1 and not include_draft:
        # 草稿对学生表现为"不存在"，不能让人靠猜 id 提前看到没发布的公告
        raise BusinessException(message="公告不存在")
    return AnnouncementResponse.model_validate(item)


def _clean_text(value: str, label: str) -> str:
    """去掉首尾空白；全是空白的当作没填。

    schema 的 min_length 拦不住 "   "：长度是 3，但用户看到的标题是空的。
    """
    value = value.strip()
    if not value:
        raise BusinessException(message=f"{label}不能为空")
    return value


def create_announcement(
    db: Session, current_user: User, data: AnnouncementCreateRequest
) -> AnnouncementResponse:
    item = Announcement(
        title=_clean_text(data.title, "标题"),
        content=_clean_text(data.content, "正文"),
        pinned=data.pinned,
        status=data.status,
        publisher_id=current_user.id,
        publisher_name=current_user.name or current_user.username,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return AnnouncementResponse.model_validate(item)


def update_announcement(
    db: Session, announcement_id: int, data: AnnouncementUpdateRequest
) -> AnnouncementResponse:
    item = db.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not item:
        raise BusinessException(message="公告不存在")

    fields = data.model_dump(exclude_unset=True)
    if "title" in fields:
        item.title = _clean_text(fields["title"], "标题")
    if "content" in fields:
        item.content = _clean_text(fields["content"], "正文")
    if "pinned" in fields:
        item.pinned = fields["pinned"]
    if "status" in fields:
        item.status = fields["status"]
    db.commit()
    db.refresh(item)
    return AnnouncementResponse.model_validate(item)


def delete_announcement(db: Session, announcement_id: int) -> None:
    deleted = (
        db.query(Announcement).filter(Announcement.id == announcement_id).delete()
    )
    if not deleted:
        raise BusinessException(message="公告不存在")
    db.commit()
