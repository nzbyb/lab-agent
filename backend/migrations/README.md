# 数据库迁移（Alembic）

表结构由 Alembic 管，**不再靠 `Base.metadata.create_all`**。
那玩意儿只建缺失的表，给已有表加列、改列、加索引一概不管，而且不报错——
上次给 `labs` 加"周末时段"两列时就是这么卡住的，最后只能手工去 Navicat 跑 SQL。

## 常用命令

都在 `backend/` 目录下执行：

```bash
.venv\Scripts\python -m alembic current          # 现在在哪个版本
.venv\Scripts\python -m alembic history          # 迁移历史
.venv\Scripts\python -m alembic upgrade head     # 升到最新
.venv\Scripts\python -m alembic downgrade -1     # 退回上一版
```

改完模型之后生成新迁移：

```bash
.venv\Scripts\python -m alembic revision --autogenerate -m "加了什么"
```

**生成完一定要打开那个文件读一遍。** autogenerate 只是比对模型和数据库的差异，
它不知道你的意图，会自动生成 `DROP TABLE` / `DROP COLUMN` 这种删数据的操作。
尤其是：**模型里删掉一个 import，会被理解成"这张表不要了"**。

## 应用启动时会自动升级

`app/main.py` 的 lifespan 里会调 `run_migrations()`（`app/database.py`），
所以正常跑服务、跑 Docker 都不用你手动执行 `upgrade`。

## 三种库分别怎么走

| 库的情况 | 会发生什么 |
| --- | --- |
| **全新的空库**（新克隆的仓库、Docker 新卷、CI 新建的测试库） | 从 `0001` 开始跑，一次把 6 张表建出来 |
| **装 Alembic 之前就建好表的库**（本机开发库、Docker 旧卷） | 先 `stamp 0001`（只写版本号，不执行 DDL），再从 `0002` 往后升 |
| **已经有 alembic_version 的库** | 正常升级 |

判断依据是"库里有没有表、有没有 alembic_version"，写在 `run_migrations()` 里。
`0001` 是**基线**，对应的是接入 Alembic 那一刻的完整结构，别删也别改它。

## 两个坑

**1. `alembic.ini` 必须保持纯 ASCII，不能有中文注释。**
Alembic 读这个文件用的是系统本地编码（`alembic/util/compat.py` 里写死 `encoding="locale"`）。
中文 Windows 的本地编码是 GBK，只要 ini 里有一个非 ASCII 字节，**所有 alembic 命令**
在启动前就抛 `UnicodeDecodeError`。而 Linux 容器里本地编码是 UTF-8，同一个文件在那儿好好的
——所以这个坑**只在 Windows 上炸**，最难查的那种。中文说明就写在这个 README 和 `.py` 文件里
（Python 源码默认按 UTF-8 读，不受影响）。

**2. 迁移目前假设单进程。**
`run_migrations()` 在应用启动时跑，Dockerfile 的 CMD 也刻意没加 `--workers`。
真要开多 worker，每个进程都会走到这里、并发跑 DDL 会撞车。
那时候要么把迁移挪到部署流程里单独执行，要么用 MySQL 的 `GET_LOCK` 包一层
（`app/services/reservation_service.py` 里已经有现成用法）。
