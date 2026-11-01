from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.models.favorite import Favorite, LabView
from app.models.lab import Lab
from app.models.user import User
from app.schemas.lab import LabResponse
from app.services import lab_service

RECENT_VIEW_LIMIT = 10


def _get_lab(db: Session, lab_id: int) -> Lab:
    lab = db.query(Lab).filter(Lab.id == lab_id).first()
    if not lab:
        raise BusinessException(message="实验室不存在")
    return lab


def _labs_in_order(db: Session, lab_ids: list[int]) -> list[Lab]:
    """按给定顺序把实验室取出来。

    一次 IN 查询而不是逐条查：收藏列表最多几十条，逐条查就是几十次往返。
    用 dict 重排是因为 IN 查询回来的顺序由数据库决定，跟传进去的无关。
    """
    if not lab_ids:
        return []
    labs = db.query(Lab).filter(Lab.id.in_(lab_ids)).all()
    by_id = {lab.id: lab for lab in labs}
    # 查的过程中实验室可能被管理员删掉了，按原顺序过滤掉不存在的即可
    return [by_id[lab_id] for lab_id in lab_ids if lab_id in by_id]


def add_favorite(db: Session, current_user: User, lab_id: int) -> None:
    """幂等：已经收藏过的再点一次不报错，结果都是"已收藏"。"""
    _get_lab(db, lab_id)
    exists = (
        db.query(Favorite)
        .filter(Favorite.user_id == current_user.id, Favorite.lab_id == lab_id)
        .first()
    )
    if exists:
        return

    db.add(Favorite(user_id=current_user.id, lab_id=lab_id))
    try:
        db.commit()
    except IntegrityError:
        # 两个请求同时插：唯一索引拦住第二个。这不是错误，结果已经达成。
        db.rollback()


def remove_favorite(db: Session, current_user: User, lab_id: int) -> None:
    """幂等：本来就没收藏，删一次也当成功。"""
    db.query(Favorite).filter(
        Favorite.user_id == current_user.id, Favorite.lab_id == lab_id
    ).delete()
    db.commit()


def list_favorite_ids(db: Session, current_user: User) -> list[int]:
    """列表页拿它决定每张卡片的心形是实心还是空心。"""
    rows = (
        db.query(Favorite.lab_id)
        .filter(Favorite.user_id == current_user.id)
        .all()
    )
    return [row[0] for row in rows]


def list_favorites(db: Session, current_user: User) -> list[LabResponse]:
    ids = [
        row[0]
        for row in db.query(Favorite.lab_id)
        .filter(Favorite.user_id == current_user.id)
        .order_by(Favorite.id.desc())
        .all()
    ]
    return [
        lab_service.to_lab_response(lab) for lab in _labs_in_order(db, ids)
    ]


def record_view(db: Session, current_user: User, lab_id: int) -> None:
    """进一次详情页记一次；同一间实验室只保留最后一次的时间。"""
    _get_lab(db, lab_id)
    view = (
        db.query(LabView)
        .filter(LabView.user_id == current_user.id, LabView.lab_id == lab_id)
        .first()
    )
    if view:
        view.view_time = datetime.now()
    else:
        db.add(
            LabView(user_id=current_user.id, lab_id=lab_id, view_time=datetime.now())
        )
    try:
        db.commit()
    except IntegrityError:
        # 首次浏览并发进来两条，唯一索引拦住第二条；把时间补刷一下即可
        db.rollback()
        db.query(LabView).filter(
            LabView.user_id == current_user.id, LabView.lab_id == lab_id
        ).update({LabView.view_time: datetime.now()})
        db.commit()


def list_recent_views(
    db: Session, current_user: User, limit: int = RECENT_VIEW_LIMIT
) -> list[LabResponse]:
    limit = max(1, min(limit, 50))
    ids = [
        row[0]
        for row in db.query(LabView.lab_id)
        .filter(LabView.user_id == current_user.id)
        .order_by(LabView.view_time.desc())
        .limit(limit)
        .all()
    ]
    return [
        lab_service.to_lab_response(lab) for lab in _labs_in_order(db, ids)
    ]
