from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.common.exceptions import BusinessException

from app.database import get_db
from app.models.user import User
from app.utils.jwt import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    try:
        payload = decode_access_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录"
        )
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的登录凭证"
        )
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在"
        )
    if user.status != 1:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户被禁用"
        )

    # 令牌版本号：改密码时 users.token_version 会 +1，于是该用户此前签发的所有令牌
    # 都在这里对不上号。这个比对**不额外花一次查询**——上面那句 db.query(User) 本来
    # 每个请求就查一次。
    #
    # `.get("ver", 0)` 的兜底不是随手写的：加这一列**之前**签发的令牌里没有 ver 声明，
    # 而老库迁移时 token_version 一律补 0，两边都按 0 算就对得上，所以部署这一版不会
    # 把已登录的人全踢下线。代价是上线前就改过密码、握着旧令牌的人要等下次改密码才失效。
    #
    # 改密码、重置密码、退出登录都会让这一列 +1，所以文案只能是中性的
    # "登录已失效"——写"密码已变更"会在用户只是点了退出登录时撒谎。
    if payload.get("ver", 0) != (user.token_version or 0):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录"
        )
    return user


def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise BusinessException(message="无权限访问", code=403)
    return current_user
