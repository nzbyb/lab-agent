from sqlalchemy.orm import sessionmaker, DeclarativeBase, Mapped, mapped_column
from sqlalchemy import create_engine, DateTime
from app.config import settings
from datetime import datetime

# hide_parameters 让 SQLAlchemy 不要在异常消息里带上绑定参数，
# 不然一旦有异常冒到日志或响应里，就等于把用户数据一起泄出去了。
engine = create_engine(settings.DATABASE_URL, hide_parameters=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Base(DeclarativeBase):
    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="主键ID", sort_order=-1
    )
    create_time: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, comment="创建时间"
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )
