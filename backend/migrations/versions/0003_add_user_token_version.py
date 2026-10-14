"""给 users 加令牌版本号 token_version

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-14

改密码之后，**此前签发出去的令牌要立刻失效**——不然抓走令牌的人还能一直用到
过期为止（默认 24 小时），改密码就只是改了个寂寞。

做法是给每个用户一个版本号：签发令牌时写进 JWT 的 `ver` 声明，校验令牌时跟库里
这一列比一次，对不上就 401。改密码时把它 +1，该用户所有旧令牌下一次请求就完了。

为什么一个整数就够、不用会话表或 Redis：
需求是"让某个人**全部**旧令牌失效"，而不是"精确吊销某一枚"。一个版本号就能 O(1)
做到，而且它存在共享的 MySQL 里，将来多机部署天然生效（Redis 解决的是限流那种
跨进程计数，不是这件事）。

`server_default="0"` **不能省**：这是给**已经有行**的表加 NOT NULL 列，没有默认值
MySQL 不知道该给老行填什么，直接报错。有了它，老行一律补 0，而"加这一列之前签发的
令牌"没有 ver 声明、校验时也按 0 算（见 app/dependencies/auth.py），两边对得上，
所以部署这一版**不会把所有人踢下线**。

代价写在明处：上线之前就改过密码、且当时那枚旧令牌还在的人，这次上线救不了他，
得等他下次再改密码。要"上线即全清"只能换 JWT_SECRET_KEY，那是全员掉线，不划算。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_COLUMN_COMMENT = "令牌版本号: 改密码时+1, 使此前签发的令牌全部失效"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "token_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment=_COLUMN_COMMENT,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
