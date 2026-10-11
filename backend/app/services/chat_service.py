import json
import logging
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.response import PageResponse
from app.database import SessionLocal
from app.models.chat import ChatConversation, ChatMessage
from app.schemas.chat import ChatConversationResponse, ChatMessageResponse

logger = logging.getLogger(__name__)

# 每个用户最多保留多少条会话，超出的连同消息一起删。
# 改它要连着 tests/test_chat_history.py 里那条造 51 条删 1 条的用例一起改。
_MAX_CONVERSATIONS = 50

# 标题取首条提问，超长截断。列宽 60，留 3 个字符给省略号。
_TITLE_MAX = 60


def _make_title(text: str) -> str:
    """把首条提问压成一行短标题。"""
    text = (text or "").strip().replace("\n", " ").replace("\r", " ")
    if len(text) > _TITLE_MAX:
        return text[: _TITLE_MAX - 3] + "..."
    return text


def extract_new_user_message(data) -> str | None:
    """挑出「这一轮新提交的那条用户提问」，没有就返回 None。

    判据是**位置**，不是内容：前端把新提问 push 到末尾之后，才用同一份列表拼出
    history 发过来，所以新提问必然是最后一条。不能用「和库里最后一条比内容」——
    用户重复问同一句话是完全合法的，按内容比会被误判成重发而漏存。
    也不能用「在历史里找最后一条 user」——万一最后一条是 assistant（别的客户端
    拼的请求体），那会把**上一轮**的提问再存一遍。
    """
    if not data.messages:
        return None
    last = data.messages[-1]
    if last.role != "user":
        return None
    text = last.content.strip()
    return text or None


def _get_or_create(
    db: Session, user_id: int, session_key: str, first_content: str
) -> ChatConversation:
    """按 (用户, session_key) 取会话，没有就建。

    建的时候要处理并发：两个标签页同时首次发消息，两边都查到「没有」、都去 INSERT，
    后提交的那条会撞上唯一约束。撞了就回滚再查一次——另一条已经建好了。
    """
    conv = (
        db.query(ChatConversation)
        .filter(
            ChatConversation.user_id == user_id,
            ChatConversation.session_key == session_key,
        )
        .first()
    )
    if conv is not None:
        return conv

    conv = ChatConversation(
        user_id=user_id, session_key=session_key, title=_make_title(first_content)
    )
    db.add(conv)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        conv = (
            db.query(ChatConversation)
            .filter(
                ChatConversation.user_id == user_id,
                ChatConversation.session_key == session_key,
            )
            .first()
        )
        # 重查还查不到，说明不是并发撞车而是别的问题，让它冒出去
        if conv is None:
            raise
    return conv


def _prune_old_conversations(db: Session, user_id: int) -> None:
    """超出保留上限的老会话连同消息一起删。

    先把该留的 id 查出来、在 Python 里切出要删的，再删——**不写成子查询**：
    MySQL 不允许在删除一张表时从同一张表里取子查询（错误 1093）。
    """
    ids = [
        row[0]
        for row in db.query(ChatConversation.id)
        .filter(ChatConversation.user_id == user_id)
        # 平手按 id 兜底，顺序才是确定的
        .order_by(ChatConversation.update_time.desc(), ChatConversation.id.desc())
        .all()
    ]
    stale_ids = ids[_MAX_CONVERSATIONS:]
    if not stale_ids:
        return

    # 项目里没有级联删除（既有模型都是裸 ForeignKey），消息必须手工先删。
    db.query(ChatMessage).filter(ChatMessage.conversation_id.in_(stale_ids)).delete(
        synchronize_session=False
    )
    db.query(ChatConversation).filter(ChatConversation.id.in_(stale_ids)).delete(
        synchronize_session=False
    )
    db.commit()


def record_user_turn(user_id: int, data) -> int | None:
    """阶段 A：用户提问落库，返回会话的整型 id（拿不到就 None）。

    **自己开一个 Session**，不用请求注入的那个：这个方法是在流式生成器开始跑之前
    调用的，但调用点之后 Session 很快会被 FastAPI 关掉，用独立的 Session 才不受影响。

    这个方法**绝不往外抛**：写历史失败不该让用户连话都问不出去。
    """
    session_key = getattr(data, "session_key", None)
    content = extract_new_user_message(data)
    if not session_key or content is None:
        return None

    db = SessionLocal()
    try:
        conv = _get_or_create(db, user_id, session_key, content)
        db.add(
            ChatMessage(conversation_id=conv.id, role="user", content=content, steps=None)
        )
        # 会话行必须显式改一次。数据库只在**这一行本身**被 UPDATE 时才自动记时间，
        # 只往里插消息的话会话行的时间不动——历史列表按时间倒序时，
        # 刚聊完的会话不会冒到最上面。
        conv.update_time = datetime.now()
        db.commit()
        conv_id = conv.id
        _prune_old_conversations(db, user_id)
        return conv_id
    except Exception:
        logger.exception("记录用户提问失败")
        return None
    finally:
        db.close()


def record_assistant_turn(
    user_id: int, session_key: str | None, content: str, steps: list | None
) -> None:
    """阶段 B：助手回复落库。

    调用点在流式生成器的 finally 里，所以**用户中途关网页也会走到这里**——这正是
    把落库放这儿（而不是循环之后）的原因。由此带来两条硬约束：
      1. 全程同步、不许 await（同步 SQLAlchemy 正好合适）；
      2. 绝不许往外抛。在取消清理的过程中抛出新异常会顶掉原本的取消信号，
         引发 anyio 告警，还可能把已经发完的流打崩。
    """
    content = (content or "").strip()
    # 正文和过程都空，这一轮没有任何东西值得存
    if not session_key or (not content and not steps):
        return

    db = SessionLocal()
    try:
        conv = (
            db.query(ChatConversation)
            .filter(
                ChatConversation.user_id == user_id,
                ChatConversation.session_key == session_key,
            )
            .first()
        )
        # 会话被保留上限删掉了（上一轮写用户提问时删的），这条回复就无处可挂
        if conv is None:
            return
        db.add(
            ChatMessage(
                conversation_id=conv.id,
                role="assistant",
                content=content,
                steps=json.dumps(steps, ensure_ascii=False) if steps else None,
            )
        )
        conv.update_time = datetime.now()
        db.commit()
        _prune_old_conversations(db, user_id)
    except Exception:
        logger.exception("记录助手回复失败")
    finally:
        db.close()


def list_conversations(
    db: Session, user_id: int, page: int, page_size: int
) -> PageResponse:
    """当前用户的历史会话列表。

    只有本人可见，管理员也看不到别人的——这一点**刻意偏离**预约那边的
    「管理员看全库」惯例：对话内容是私事，不是需要被审核的业务数据。
    所以这里一律按 user_id 过滤，**不写 role 判断**。
    """
    query = db.query(ChatConversation).filter(ChatConversation.user_id == user_id)
    total = query.count()
    items = (
        query.order_by(ChatConversation.update_time.desc(), ChatConversation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PageResponse(
        list=[ChatConversationResponse.model_validate(item) for item in items],
        total=total,
    )


def get_messages(db: Session, user_id: int, conversation_id: int):
    """某条会话的全部消息。

    查不到、或不属于当前用户，一律返回 None（接口给 200 + data=null）。

    这里**不用 403**是刻意的：前端每次进页面都会拿本地记着的会话来恢复，如果它
    已经被保留上限删掉了，抛业务异常会让请求拦截器弹一条红色错误提示——用户什么
    都没干就看到报错。返回 null 让前端安静地开一条新会话。
    顺带也不泄露「这个 id 到底存不存在」。
    """
    conv = (
        db.query(ChatConversation)
        .filter(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == user_id,
        )
        .first()
    )
    if conv is None:
        return None
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.conversation_id == conv.id)
        .order_by(ChatMessage.id.asc())
        .all()
    )
    return [
        ChatMessageResponse(
            id=row.id,
            role=row.role,
            content=row.content,
            # 存的是 JSON 文本，出参给结构化数组；解析失败当没有过程，
            # 不能让一条坏数据把整次回看打挂
            steps=_loads_steps(row.steps),
            create_time=row.create_time,
        )
        for row in rows
    ]


def _loads_steps(raw: str | None):
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("会话消息里的 steps 不是合法 JSON，已忽略")
        return None
    return parsed if isinstance(parsed, list) else None


def delete_conversation(db: Session, user_id: int, conversation_id: int) -> bool:
    """删除一条会话及其全部消息。删掉了返回 True，不是自己的返回 False。

    删除是用户明确点的操作，不存在「安静失败」的需要，所以这里和 get_messages
    不同——由路由层把 False 变成一条明确的业务错误。
    """
    conv = (
        db.query(ChatConversation)
        .filter(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == user_id,
        )
        .first()
    )
    if conv is None:
        return False

    # 没有级联删除，消息手工先删（顺序不能反，外键在那里）
    db.query(ChatMessage).filter(ChatMessage.conversation_id == conv.id).delete(
        synchronize_session=False
    )
    db.delete(conv)
    db.commit()
    return True
