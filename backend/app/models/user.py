from app.database import Base
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"comment": "用户信息表"}
    username: Mapped[str] = mapped_column(String(50), comment="账号", nullable=False)
    password: Mapped[str] = mapped_column(String(255), comment="密码", nullable=False)
    name: Mapped[str] = mapped_column(String(50), comment="名称", nullable=False)
    role: Mapped[str] = mapped_column(
        String(50), comment="角色: student-学生, admin-管理员", nullable=False
    )
    email: Mapped[str | None] = mapped_column(String(50), comment="邮箱")
    phone: Mapped[str | None] = mapped_column(String(50), comment="手机号")
    avatar: Mapped[str | None] = mapped_column(String(50), comment="头像")
    status: Mapped[int] = mapped_column(default=1, comment="状态: 1-正常, 0-禁用")
    # 令牌版本号。签发令牌时会被写进 JWT 的 ver 声明，校验令牌时跟这一列比一次，
    # 对不上就 401——改密码时把它 +1，该用户此前签发的令牌就全废了。
    #
    # default=0 是 Python 端的默认值，**不能省**：make_user / register / create_user
    # 三处都是直接 `User(...)` 不带这个字段，少了它 INSERT 会因为 NOT NULL 失败。
    # server_default="0" 是给"给已有表加列"用的（老行补 0），也让 create_all 建出来的
    # DDL 跟迁移建出来的保持一致——两条路径产出的列定义不一样，是以后最容易踩的坑。
    token_version: Mapped[int] = mapped_column(
        default=0,
        server_default="0",
        comment="令牌版本号: 改密码时+1, 使此前签发的令牌全部失效",
    )
