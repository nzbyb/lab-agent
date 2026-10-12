from datetime import datetime

from app.models.lab import Lab
from app.schemas.lab import (
    LabResponse,
    LabUpdateRequest,
    LabCreateRequest,
)
from sqlalchemy.orm import Session
from app.common.exceptions import BusinessException
from app.common.response import PageResponse

# 周六、周日。datetime.weekday() 里周一是 0，所以周末是 5 和 6。
WEEKEND_DAYS = (5, 6)

WEEKDAY_NAMES = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def describe_moment(when: datetime) -> str:
    """把时刻写成"2026-10-12 星期一 21:39"这种给人看的样子。

    给 AI 用：它自己不知道"现在几点、今天星期几"，而开放时间恰好两样都依赖。
    """
    return f"{when.strftime('%Y-%m-%d %H:%M')}（{WEEKDAY_NAMES[when.weekday()]}）"


def _now() -> datetime:
    """现在几点。

    特意包成函数而不是到处直接写 datetime.now()：今日时段和"此刻开着没"
    都跟着"现在"走，要钉死时间做测试就得有个能替换的入口。
    """
    return datetime.now()


def resolve_open_hours(lab: Lab, date: str) -> tuple[str | None, str | None]:
    """这一天这间实验室实际生效的 (开门, 关门)。两个都是 None = 当天不开放。

    **全项目只有这一处决定"某一天该用哪套时段"**，其他所有地方
    （预约校验、空闲时段、AI 工具、界面）都从这里派生，别再各判各的。

    date 必须是 YYYY-MM-DD（调用方保证：预约请求由 schema 规范化过，
    空闲时段查询在入口规范化过）。这里不做格式兜底。

    "有没有设"一律用真假值判断，不是 `is None`：管理端表单里把时间选择器
    清空后发上来的是空字符串。只认 None 的话，管理员一旦填过周末时段，
    就再也改不回"周末不开放"了。
    """
    on = datetime.strptime(date, "%Y-%m-%d")
    if on.weekday() in WEEKEND_DAYS:
        open_time, close_time = lab.weekend_open_time, lab.weekend_close_time
    else:
        open_time, close_time = lab.open_time, lab.close_time
    if not open_time or not close_time:
        return None, None
    return open_time, close_time


def is_open_at(lab: Lab, when: datetime) -> bool:
    """when 那一刻，这间实验室是不是开着。

    1. 被停用的（status != 1）一律不算开放。少了这条，界面会对一间
       约不上的实验室显示"开放中"——预约那边可是会拿 status 拒人的。
    2. 开门和关门两个端点都算在内。跟预约校验的边界保持一致
       （那边是 start < 开门 或 end > 关门 才拒绝），否则 20:00 整
       那一刻会出现"界面说开着、下单说关了"。
    3. 星期几和时分都从同一个 when 取，不许另外传日期字符串进来，
       不然跨午夜时两者会对不上。
    """
    if lab.status != 1:
        return False
    open_time, close_time = resolve_open_hours(lab, when.strftime("%Y-%m-%d"))
    if open_time is None or close_time is None:
        return False
    current = when.strftime("%H:%M")
    return open_time <= current <= close_time


def to_lab_response(lab: Lab, now: datetime | None = None) -> LabResponse:
    """LabResponse 的唯一出口。

    今日时段和 open_now 必须在这里算——它们依赖"现在几点"，而
    "哪天用哪套时段"的规则只写在 resolve_open_hours 里。

    字段一个个写出来而不是 model_validate(lab)：这三个计算字段故意没有默认值，
    将来谁往 LabResponse 里加了字段，这里会当场报错，而不是悄悄回一个空值。
    """
    when = now or _now()
    today_open, today_close = resolve_open_hours(lab, when.strftime("%Y-%m-%d"))
    return LabResponse(
        id=lab.id,
        name=lab.name,
        description=lab.description,
        img=lab.img,
        location=lab.location,
        capacity=lab.capacity,
        open_time=lab.open_time,
        close_time=lab.close_time,
        weekend_open_time=lab.weekend_open_time,
        weekend_close_time=lab.weekend_close_time,
        status=lab.status,
        today_open_time=today_open,
        today_close_time=today_close,
        open_now=is_open_at(lab, when),
    )


def get_lab_page_list(
    db: Session,
    page: int,
    page_size: int,
    keywords: str | None = None,
    status: int | None = None,
):
    query = db.query(Lab)
    if keywords:

        query = query.filter(Lab.name.ilike(f"%{keywords}%"))
    # 必须写 is not None：0 是合法状态（已关闭），用 if status 会被当成"没传"，
    # 想看关闭中的实验室反而拿到全部。
    if status is not None:
        query = query.filter(Lab.status == status)
    total = query.count()
    items = (
        query.order_by(Lab.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    # 整页共用一个"现在"：逐行各取一次的话，正好跨过整点那一秒时，
    # 同一页里会出现有的行说开放、有的行说关闭。
    when = _now()
    return PageResponse(
        list=[to_lab_response(item, when) for item in items], total=total
    )


def get_lab(db: Session, lab_id: int):
    lab = db.query(Lab).filter(Lab.id == lab_id).first()
    if not lab:
        raise BusinessException(message="实验室不存在")
    return to_lab_response(lab)


def create_lab(db: Session, data: LabCreateRequest):
    exist = db.query(Lab).filter(Lab.name == data.name).first()
    if exist:
        raise BusinessException(message="实验室已存在")
    lab = Lab(**data.model_dump())
    db.add(lab)
    db.commit()
    db.refresh(lab)
    return to_lab_response(lab)


def update_lab(db: Session, lab_id: int, data: LabUpdateRequest):
    lab = db.query(Lab).filter(Lab.id == lab_id).first()
    if not lab:
        raise BusinessException(message="实验室不存在")
    payload = data.model_dump(exclude_none=True)
    for filed, value in payload.items():
        setattr(lab, filed, value)

    db.commit()
    db.refresh(lab)
    return to_lab_response(lab)


def delete_lab(db: Session, lab_id: int):
    lab = db.query(Lab).filter(Lab.id == lab_id).first()
    if not lab:
        raise BusinessException(message="实验室不存在")
    db.delete(lab)
    db.commit()
