import hashlib
import logging
import threading

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.utils import embedding_functions

from app.config import BASE_DIR
from app.database import SessionLocal
from app.models.lab import Lab
# 开放时间这套规则的唯一判断点在 lab_service.resolve_open_hours。
# 渲染知识库文档时绕一圈去问它，而不是自己读 lab.open_time——
# 否则规则一变（比如以后加节假日），文档就又跟代码对不上了，
# 而这正是这次要修的病根。
from app.services import lab_service

logger = logging.getLogger(__name__)

KB_DIR = BASE_DIR / "data" / "kb"
CHROMA_DIR = BASE_DIR / "data" / "chroma"
EMBEDDING_MODEL_NAME = "BAAI/bge-small-zh-v1.5"

# 这份文档不放在仓库里手工维护，每次启动和每次改动实验室都按数据库重画一遍。
OPEN_HOURS_DOC_NAME = "开放时间.md"

# 渲染时拿来"问"resolve_open_hours 的两个日子：2024-01-03 是周三、01-06 是周六。
# 挑哪一年无所谓，要的只是"一个星期几"，所以钉死成常量，渲染结果才稳定
# （不然同样的数据每次生成出来的内容会跟着今天星期几变）。
_RENDER_WEEKDAY = "2024-01-03"
_RENDER_WEEKEND = "2024-01-06"

_collection = None

_embedding_fn = None

# 保护"建集合"和"重建索引"。检索本身在锁外面跑：一条回复里可以有好几个
# 工具调用并发查资料，让它们排队就没意义了。
_lock = threading.Lock()


def get_embedding_fn():
    global _embedding_fn
    if _embedding_fn is not None:
        return _embedding_fn
    _embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL_NAME
    )
    return _embedding_fn


def render_open_hours_doc(labs) -> str:
    """把实验室渲染成 开放时间.md 的内容。纯函数，不碰文件也不碰数据库。"""
    lines = [
        "# 实验室开放时间",
        "",
        "> 本文件由系统按数据库里的实验室配置自动生成，请不要手工修改——改了会被覆盖。",
        "> 需要调整开放时间，请走管理端的「实验室管理」。",
        "",
    ]
    for lab in labs:
        if lab.status != 1:
            # 停用的也列出来。直接跳过的话，"文档里没有这家实验室"和
            # "这家实验室不开放"就分不清了。
            lines.append(f"- {lab.name}：已停用，不开放预约")
            continue
        weekday_open, weekday_close = lab_service.resolve_open_hours(
            lab, _RENDER_WEEKDAY
        )
        weekend_open, weekend_close = lab_service.resolve_open_hours(
            lab, _RENDER_WEEKEND
        )
        # resolve_open_hours 要么两个都给、要么两个都是 None，判一个就够
        weekday_text = (
            f"周一至周五 {weekday_open}-{weekday_close}"
            if weekday_open
            else "周一至周五不开放"
        )
        weekend_text = (
            f"周六、周日 {weekend_open}-{weekend_close}"
            if weekend_open
            else "周六、周日不开放"
        )
        lines.append(f"- {lab.name}：{weekday_text}；{weekend_text}")
    lines += ["", "开放时段内仍需先预约并通过审核，不能直接进入。", ""]
    return "\n".join(lines)


def rebuild_open_hours_doc() -> bool:
    """按数据库重建 开放时间.md，返回文件是否真的变了。

    **不抛异常**：调用它的路径（启动时、管理员保存/删除实验室之后）业务动作
    都已经提交成功了，知识库文档没跟上不该让用户看到 500——他的修改其实
    已经生效。真出错时日志里有完整堆栈。

    只写文件、**不碰向量库**：重建索引落在下一次检索那一侧（见 _sync_index）。
    否则"保存实验室"这个请求就依赖向量库能不能用，还会被 bge 模型在 CPU 上
    几秒钟的加载卡住。
    """
    try:
        with SessionLocal() as db:
            labs = db.query(Lab).order_by(Lab.id).all()
            # 取值必须在会话关掉之前做完，不然后面碰 ORM 对象会 DetachedInstanceError
            text = render_open_hours_doc(labs)
        return _write_if_changed(KB_DIR / OPEN_HOURS_DOC_NAME, text)
    except Exception:
        logger.exception("重建实验室开放时间文档失败，知识库里还是旧的那份")
        return False


def _write_if_changed(path, text: str) -> bool:
    """内容一模一样就不动文件，返回是否写过。

    不写的话 mtime 和指纹都不变，也就不会触发一次毫无必要的重建索引——
    每次保存实验室都重算一遍 embedding 是好几秒钟的事。
    """
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def _fingerprint_path():
    # 放在 chroma 目录里：将来谁把 data/chroma 整个删掉重建，
    # 指纹也跟着没了，于是必然重建一次，不会出现"索引空了却以为还是新的"。
    return CHROMA_DIR / "kb_fingerprint.txt"


def _fingerprint() -> str:
    """data/kb 下所有 md 的指纹（文件名 + 内容）。

    用它代替单独的"脏标记"：管理端改完实验室只是重写了 md，不需要再通知
    谁；下一次检索发现指纹对不上，自然就去重建了。读四个几 KB 的文件，
    比重算一次 embedding 便宜得多。
    """
    digest = hashlib.sha256()
    for path in sorted(KB_DIR.glob("*.md")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _read_stored_fingerprint():
    try:
        return _fingerprint_path().read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _sync_index(col: Collection) -> None:
    """文件变了就把索引补齐，没变就直接返回。"""
    current = _fingerprint()
    # 快路径不拿锁：绝大多数检索都是这条路径，不该为了一把锁排队。
    if _read_stored_fingerprint() == current and col.count() > 0:
        return
    with _lock:
        # 等锁的这段时间里，别的线程可能已经重建完了
        if _read_stored_fingerprint() == current and col.count() > 0:
            return
        _rebuild(col, current)


def _rebuild(col: Collection, fingerprint: str) -> None:
    """就地补齐索引：有的 upsert，多出来的删掉。

    **不能"先删集合再重建"**：一旦 embed 中途失败，好端端的索引也没了，
    而 AI 只会静默地答"没有检索到相关的资料"，不报任何错，看起来像知识库
    本来就是空的。upsert 最坏也只是"还是旧内容"，至少查得到。

    指纹只在**全部成功之后**才写。先写的话，一次失败会被记成"已完成"，
    之后再也不会重试。
    """
    ids = []
    docs = []
    metas = []
    for path in sorted(KB_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        ids.append(path.stem)
        docs.append(text)
        metas.append({"source": path.name})

    if ids:
        col.upsert(ids=ids, documents=docs, metadatas=metas)

    # 文件被删掉或改名之后，旧条目还留在集合里，检索时照样会被命中
    known = set(ids)
    stale = [old for old in col.get(include=[])["ids"] if old not in known]
    if stale:
        col.delete(ids=stale)

    path = _fingerprint_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fingerprint, encoding="utf-8")


def _create_collection() -> Collection:
    KB_DIR.mkdir(parents=True, exist_ok=True)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    # 必须显式传 embedding function，不能留 None。
    # 传 None 时 chromadb 的冲突校验整段被跳过（collection_configuration.py 里那句
    # `if embedding_function is not None`），所以现在能跑——靠的是 data/chroma 里持久化的
    # known 配置（name=sentence_transformer, model_name=BAAI/bge-small-zh-v1.5）被自动恢复。
    # 但一旦 data/chroma 被删掉重建，就没有持久化配置可继承，会退回 chromadb 自带的
    # 英文默认模型（all-MiniLM-L6-v2），中文检索静默劣化、且不报任何错。
    # 传进去的实例与持久化配置同名（name() 都是 "sentence_transformer"）且参数逐字段相同
    # （device="cpu"、normalize_embeddings=False 都是该类的默认值），所以不会触发冲突。
    return client.get_or_create_collection(
        name="lab_kb", embedding_function=get_embedding_fn()
    )


def get_collection() -> Collection:
    """拿到集合，并保证里面的内容和 data/kb 里的文件一致。"""
    global _collection
    if _collection is None:
        with _lock:
            if _collection is None:
                _collection = _create_collection()
    _sync_index(_collection)
    return _collection


def warmup():
    """启动预热。

    顺序不能反：先把 开放时间.md 按数据库重画一遍，再建/补齐索引——
    反过来的话索引里进的是旧文档，要等下一次文件变动才会纠正。
    """
    rebuild_open_hours_doc()
    col = get_collection()
    if col.count() > 0:
        col.query(query_texts=["预热"], n_results=1)


def search(query: str):
    col = get_collection()
    if col.count() == 0:
        return ""
    limit = min(5, col.count())
    res = col.query(query_texts=[query], n_results=limit)
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    distances = (res.get("distances") or [[]])[0]

    score_parts = []
    for doc, metas, dist in zip(docs, metas, distances):

        score = 1 / (1 + dist)
        if score < 0.5:
            continue
        name = metas.get("source") or ""
        score_parts.append({"score": score, "content": f"[{name}]\n{doc}"})

    score_parts.sort(key=lambda x: x["score"], reverse=True)
    final_parts = [item["content"] for item in score_parts[:2]]
    return "\n\n".join(final_parts)
