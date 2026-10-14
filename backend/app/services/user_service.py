from operator import or_
from app.models.user import User
from app.schemas.user import (
    UserResponse,
    UserUpdateRequest,
    UserCreateRequest,
    AdminPasswordResetRequest,
    PasswordUpdateRequest,
)
from sqlalchemy.orm import Session
from app.utils.password import hash_password, verify_password
from app.common.exceptions import BusinessException
from app.common.response import PageResponse


def get_user_info(user: User) -> UserResponse:
    return UserResponse.model_validate(user)


def update_user_info(db: Session, user: User, data: UserUpdateRequest):
    # exclude_unset 才是「只更新请求里真的带了的字段」。
    # 之前是先无条件给四个字段赋值、再拿 exclude_none 覆盖一遍——等于没防住：
    # 属性那时已经被赋成 None 了，只改手机号就会让 name 撞 NOT NULL 报 500，
    # 带上 name 时 email/avatar 又被静默清空。
    payload = data.model_dump(exclude_unset=True, exclude={"role", "status"})
    for field, value in payload.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return UserResponse.model_validate(user)


def update_password(db: Session, user: User, data: PasswordUpdateRequest):
    if not verify_password(data.old_password, user.password):
        raise BusinessException(message="原密码错误")
    if data.old_password == data.new_password:
        raise BusinessException(message="新密码不能跟原密码相同")
    user.password = hash_password(data.new_password)
    # 密码和版本号必须**在同一次 commit 里**落地。拆成两次提交会留下一个窗口：
    # 密码已经改了、旧令牌却还没失效——那正是这个方法要堵的洞。
    #
    # 这条 +1 就是"改密码后强制下线"的全部动作：该用户此前签发的所有令牌
    # （含别的设备、别的标签页）下一次请求会在 dependencies/auth.py 里对不上号被拒。
    # 当前这台设备自己也会立刻掉线，但前端本来就 logout 跳登录页，体验上无感。
    user.token_version = (user.token_version or 0) + 1
    db.commit()


def reset_password(db: Session, user_id: int, data: AdminPasswordResetRequest):
    """管理员给指定用户重置密码。

    这里同样要 token_version += 1，而且理由比本人改密码那次更硬：重置密码的
    典型场景就是"这个人的号可能被人盗了"。只换哈希不换版本号的话，盗号者手里
    那枚令牌照样有效到过期为止（默认 24 小时），重置等于白做——真正的主人反而
    以为自己已经把对方踢出去了。

    密码和版本号必须落在同一次 commit 里，理由同 update_password。
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise BusinessException(message="用户不存在")

    user.password = hash_password(data.new_password)
    user.token_version = (user.token_version or 0) + 1
    db.commit()


def get_user_page_list(
    db: Session, page: int, page_size: int, keywords: str | None = None
):
    query = db.query(User)
    if keywords:

        query = query.filter(
            or_(User.username.ilike(f"%{keywords}%"), User.name.ilike(f"%{keywords}%"))
        )
    total = query.count()
    items = (
        query.order_by(User.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PageResponse(
        list=[UserResponse.model_validate(item) for item in items], total=total
    )


def create_user(db: Session, data: UserCreateRequest):
    exist = db.query(User).filter(User.username == data.username).first()
    if exist:
        raise BusinessException(message="账号已存在")

    user = User(
        username=data.username,
        password=hash_password(data.password),
        name=data.name,
        role=data.role,
        email=data.email,
        phone=data.phone,
        avatar=data.avatar,
        status=data.status,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse.model_validate(user)


def update_user(db: Session, user_id: int, data: UserUpdateRequest):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise BusinessException(message="用户不存在")
    payload = data.model_dump(exclude_none=True)
    for filed, value in payload.items():
        setattr(user, filed, value)

    db.commit()
    db.refresh(user)
    return UserResponse.model_validate(user)


def delete_user(db: Session, user_id: int, current_user: User):
    if user_id == current_user.id:
        raise BusinessException(message="不能删除当前登录的账号")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise BusinessException(message="用户不存在")
    db.delete(user)
    db.commit()
