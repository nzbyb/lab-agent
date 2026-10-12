"""知识库「开放时间.md」由数据库生成、索引按需重建的回归用例。

背景：这份 md 原先是被 git 跟踪、手工维护的，内容跟数据库里的开放时间
对不上（只覆盖 3 间实验室、计算机实验室写的是 21:00 关门，数据库里是 20:00）。
AI 检索到的就是这份 md，于是它说的和系统实际执行的是两套。

现在这份文档由后端从 labs 表渲染，其余几份 md 仍然手工维护。
索引走"文件指纹变了才重建"，所以改了任意一份 md，不删 chroma 重启也能生效。

KB_DIR 被 conftest 的 _isolate_knowledge_base 挪到了临时目录，
这里的用例往那个临时目录里写 md。
"""

import pytest

from app.services import kb_service


class _FakeCollection:
    """假的 chroma 集合：只记下被调用了什么，不真的向量化。

    真跑 embedding 要几秒钟（CPU 上加载 bge 模型），而这里要验的是
    "怎么改索引"的步骤和顺序，跟向量本身没关系。
    """

    def __init__(self, ids=()):
        self.ids = list(ids)
        self.upserted = []
        self.deleted = []
        self.fail_upsert = False

    def count(self):
        return len(self.ids)

    def upsert(self, ids, documents, metadatas):
        if self.fail_upsert:
            raise RuntimeError("假装 embedding 挂了")
        self.upserted.append(list(ids))
        self.ids.extend(i for i in ids if i not in self.ids)

    def get(self, include=None):
        return {"ids": list(self.ids)}

    def delete(self, ids):
        self.deleted.append(list(ids))
        self.ids = [i for i in self.ids if i not in set(ids)]


def _write_md(name: str, text: str) -> None:
    kb_service.KB_DIR.mkdir(parents=True, exist_ok=True)
    (kb_service.KB_DIR / name).write_text(text, encoding="utf-8")


class TestRenderOpenHoursDoc:
    """渲染出来的内容必须能回答"这间实验室几点开、周末开不开"。"""

    def test_lists_weekday_and_weekend(self, make_lab):
        computer = make_lab(
            name="计算机实验室",
            open_time="08:00",
            close_time="20:00",
            weekend_open_time="09:00",
            weekend_close_time="17:00",
        )
        chemistry = make_lab(
            name="化学实验室",
            open_time="08:00",
            close_time="18:00",
            weekend_open_time="",
            weekend_close_time="",
        )

        text = kb_service.render_open_hours_doc([computer, chemistry])

        assert "- 计算机实验室：周一至周五 08:00-20:00；周六、周日 09:00-17:00" in text
        assert "- 化学实验室：周一至周五 08:00-18:00；周六、周日不开放" in text

    def test_marks_disabled_labs(self, make_lab):
        """停用的实验室也列出来，但要写清楚是停用而不是"某天不开放"。"""
        lab = make_lab(name="电子实验室", status=0)
        text = kb_service.render_open_hours_doc([lab])

        assert "- 电子实验室：已停用，不开放预约" in text
        assert "周一至周五" not in text

    def test_says_it_is_generated(self, make_lab):
        """文件头得写清楚是自动生成的，否则下一个人会去手改它。"""
        text = kb_service.render_open_hours_doc([make_lab()])

        assert "自动生成" in text
        assert "请不要手工修改" in text

    def test_empty_weekday_hours(self, make_lab):
        lab = make_lab(
            open_time=None,
            close_time=None,
            weekend_open_time="",
            weekend_close_time="",
        )
        text = kb_service.render_open_hours_doc([lab])

        assert "周一至周五不开放" in text


class TestRebuildDoc:
    def test_writes_the_file(self, db, make_lab):
        make_lab(name="化学实验室", weekend_open_time="", weekend_close_time="")

        assert kb_service.rebuild_open_hours_doc() is True

        text = (kb_service.KB_DIR / kb_service.OPEN_HOURS_DOC_NAME).read_text(
            encoding="utf-8"
        )
        assert "化学实验室" in text

    def test_second_call_does_not_touch_the_file(self, db, make_lab):
        """内容没变就别写。

        写了的话 mtime 变了、指纹也变了，每次保存实验室都会白白重建一次索引
        ——那是几秒钟的 embedding。
        """
        make_lab()
        assert kb_service.rebuild_open_hours_doc() is True
        assert kb_service.rebuild_open_hours_doc() is False

    def test_reflects_an_edit(self, db, make_lab):
        lab = make_lab(name="计算机实验室", open_time="08:00", close_time="20:00")
        kb_service.rebuild_open_hours_doc()

        lab.close_time = "18:00"
        db.commit()

        assert kb_service.rebuild_open_hours_doc() is True
        text = (kb_service.KB_DIR / kb_service.OPEN_HOURS_DOC_NAME).read_text(
            encoding="utf-8"
        )
        assert "周一至周五 08:00-18:00" in text

    def test_failure_is_swallowed(self, db, monkeypatch):
        """渲染失败不能让"保存实验室"这个请求 500——那边的改动已经提交了。

        这里让查库直接炸。
        """
        def boom(*args, **kwargs):
            raise RuntimeError("数据库连不上")

        monkeypatch.setattr(kb_service, "SessionLocal", boom)

        assert kb_service.rebuild_open_hours_doc() is False


class TestFingerprint:
    def test_changes_when_content_changes(self):
        _write_md("预约规则.md", "原文")
        before = kb_service._fingerprint()

        _write_md("预约规则.md", "改过的内容")

        assert kb_service._fingerprint() != before

    def test_changes_when_a_file_is_added(self):
        _write_md("预约规则.md", "原文")
        before = kb_service._fingerprint()

        _write_md("新文档.md", "新内容")

        assert kb_service._fingerprint() != before

    def test_stable_when_nothing_changes(self):
        _write_md("预约规则.md", "原文")
        assert kb_service._fingerprint() == kb_service._fingerprint()


class TestSyncIndex:
    def test_rebuilds_when_nothing_is_indexed_yet(self):
        _write_md("预约规则.md", "内容")
        col = _FakeCollection()

        kb_service._sync_index(col)

        assert col.upserted == [["预约规则"]]
        assert kb_service._read_stored_fingerprint() == kb_service._fingerprint()

    def test_skips_when_fingerprint_matches(self):
        _write_md("预约规则.md", "内容")
        col = _FakeCollection()
        kb_service._sync_index(col)

        kb_service._sync_index(col)

        assert len(col.upserted) == 1  # 第二次没有再 embed 一遍

    def test_rebuilds_when_a_file_changes(self):
        _write_md("预约规则.md", "内容")
        col = _FakeCollection()
        kb_service._sync_index(col)

        _write_md("预约规则.md", "改过的内容")
        kb_service._sync_index(col)

        assert len(col.upserted) == 2
        assert kb_service._read_stored_fingerprint() == kb_service._fingerprint()
        assert col.deleted == []  # 文件名没变，不该有东西被删

    def test_removes_stale_entries(self):
        """md 被改名或删掉之后，旧条目还留在集合里，检索时照样会被命中。"""
        _write_md("预约规则.md", "内容")
        col = _FakeCollection(ids=["早就删掉的旧文档"])
        kb_service._sync_index(col)

        assert col.deleted == [["早就删掉的旧文档"]]
        assert col.ids == ["预约规则"]

    def test_upserts_instead_of_deleting_everything(self):
        """必须就地 upsert，不能"先删集合再重建"。

        先删的话，一旦 embed 失败，好端端的索引也没了，而 AI 只会静默地
        答"没有检索到相关的资料"，看起来像知识库本来就是空的。
        """
        _write_md("预约规则.md", "内容")
        col = _FakeCollection(ids=["预约规则"])
        kb_service._sync_index(col)

        assert col.deleted == []
        assert col.upserted == [["预约规则"]]

    def test_failed_rebuild_keeps_the_old_index_and_retries_later(self):
        """失败时：旧索引还在，指纹不写，所以下次还会再试。

        指纹要是先写了，这一次失败会被记成"已完成"，之后再也不会重试。
        """
        _write_md("预约规则.md", "内容")
        col = _FakeCollection(ids=["预约规则"])
        col.fail_upsert = True

        with pytest.raises(RuntimeError):
            kb_service._sync_index(col)

        assert col.ids == ["预约规则"]  # 索引没被清掉
        assert kb_service._read_stored_fingerprint() is None  # 于是下次还会重试

    def test_retry_succeeds_after_a_failure(self):
        _write_md("预约规则.md", "内容")
        col = _FakeCollection(ids=["预约规则"])
        col.fail_upsert = True
        with pytest.raises(RuntimeError):
            kb_service._sync_index(col)

        col.fail_upsert = False
        kb_service._sync_index(col)

        assert kb_service._read_stored_fingerprint() == kb_service._fingerprint()


class TestAdminEditRefreshesDoc:
    """管理端改完实验室，文档必须跟着变——这是"统一真相来源"的落点。"""

    def test_update_endpoint_rewrites_the_doc(
        self, db, make_lab, make_user, auth_headers, client
    ):
        lab = make_lab(name="计算机实验室", open_time="08:00", close_time="20:00")
        admin = make_user(username="admin1", role="admin")
        kb_service.rebuild_open_hours_doc()

        resp = client.put(
            f"/api/lab/{lab.id}",
            json={"close_time": "18:00"},
            headers=auth_headers(admin),
        )
        assert resp.status_code == 200, resp.text

        text = (kb_service.KB_DIR / kb_service.OPEN_HOURS_DOC_NAME).read_text(
            encoding="utf-8"
        )
        assert "周一至周五 08:00-18:00" in text
