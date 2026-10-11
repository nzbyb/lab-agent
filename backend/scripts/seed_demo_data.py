"""生成演示用的预约数据。

用法（都在 backend/ 目录下执行）：
    python scripts/seed_demo_data.py                  只预演，不写库（默认）
    python scripts/seed_demo_data.py --apply          真正写入
    python scripts/seed_demo_data.py --reset --apply  先删掉本脚本以前写的行，再写
    python scripts/seed_demo_data.py --user-id 3 --apply   全部挂在 3 号账号名下

为什么默认是预演：这个脚本会往一个**真实数据库**里插行。默认只读、把要写什么
原样打出来，确认无误后再加 --apply。写库前会把四张表的行数打出来，写完再打一次，
"到底写进去没有"以行数为准，不以脚本自己说"完成"为准。

安全边界（改动这个脚本时请一并守住）：
  1. 只 INSERT，绝不 UPDATE / DELETE 既有业务数据。
  2. **绝不新建用户**。这个仓库是公开的，任何在这里硬编码的账号名/口令都会变成
     公开的默认凭据。演示行一律挂在库里**已存在**的账号名下。
  3. 不碰 labs / equipments —— 那是手工维护的基础数据（见 backend/demo_data.sql）。
  4. 每一行的 remark 末尾都带 MARKER。回滚就是对 remark 做一次 LIKE 删除，
     作用范围可以用一条 COUNT(*) 直接证明。

已知副作用：MARKER 会出现在"我的预约"的备注列里，看得见。
"""

import argparse
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

# 让 `python scripts/seed_demo_data.py` 能直接跑（不必先 pip install -e .）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, or_  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.equipment import Equipment  # noqa: E402
from app.models.lab import Lab  # noqa: E402
from app.models.reservation import Reservation  # noqa: E402
from app.models.user import User  # noqa: E402

# Windows 控制台默认 cp936，直接 print 中文会 UnicodeEncodeError。
# 这个脚本的输出全是给人看的，编码错了就等于什么都没打出来。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 每行 remark 末尾都会带上它。回滚 SQL 靠它定位，不靠 id 段或时间范围。
MARKER = "seed-demo-20261011"
# 回滚用这个模式：只认这个前缀族，覆盖以后可能新增的批次
ROLLBACK_LIKE = "%seed-demo-%"

# 趋势图的窗口是 7 天，所以 create_time 也铺在这 7 天里（下标 0 = 6 天前，6 = 今天）。
# 刻意做成有起伏而不是每天一样多：均匀分布画出来是一条平线，看不出趋势图画没画对。
# 今天给 1 条而不是 0：最后一根柱子为 0 时容易被误当成"图没渲染"。
PER_DAY = [4, 6, 5, 7, 4, 3, 1]

# 每个实验室一行：(已通过, 待审核, 已拒绝, 已取消)
# 这组数字刻意让榜首明显领先、尾部拉开差距，排行条才有看头；
# 同时保证按"有效预约"口径（status in (0,1)）算出来的进榜数是 10/6/5/2/1，
# **严格递减**，不会出现并列（并列时排序要靠 tie-break，演示数据不该依赖那个）。
# 合计 30 条；状态分布是 19 通过 / 5 待审 / 3 拒绝 / 3 取消，四段都非零。
LAB_PLAN = [
    (8, 2, 1, 1),
    (5, 1, 1, 1),
    (4, 1, 0, 1),
    (1, 1, 0, 0),
    (1, 0, 1, 0),
]

# 预约时段。互不重叠由下面的排期逻辑保证。
SLOTS = [
    ("08:00", "10:00"),
    ("10:00", "12:00"),
    ("14:00", "16:00"),
    ("16:00", "18:00"),
    ("19:00", "21:00"),
]

REMARKS = [
    "课程设计小组讨论",
    "毕业设计实验",
    "算法课课后上机",
    "竞赛集训",
    "项目组例会",
    "论文数据采集",
    "实验室开放日值班",
    "嵌入式课程实验",
]

STATUS_NAME = {0: "待审核", 1: "已通过", 2: "已拒绝", 3: "已取消"}

# Reservation 真正接受的列。build_rows 造出来的 dict 里**还多一个 lab_name**：
# 那是为了方便预演和统计而带上的展示字段，不是模型字段。
# 构造 ORM 对象时必须按这份白名单过滤，否则 SQLAlchemy 会抛
# "invalid keyword argument"——而且是在写库那一刻才抛。
MODEL_FIELDS = (
    "user_id",
    "lab_id",
    "equipment_id",
    "date",
    "start_time",
    "end_time",
    "remark",
    "status",
    "create_time",
)
# 允许出现在 row 里、但不进模型的展示字段
DISPLAY_FIELDS = ("lab_name",)


def build_rows(labs, owner_ids, today, user_id=None):
    """把 LAB_PLAN 展开成待写入的行（纯函数，不碰数据库，方便预演与核对）。

    owner_ids 是这些演示预约要挂的账号 id 列表。调用方传进来的应当**不含管理员**：
    "管理员给自己约了一间实验室"不是这个系统里会自然出现的数据。管理员的
    统计口径本来就是全库，所以演示行挂不挂在他名下都不影响管理员看到的效果。

    返回 (rows, skipped)：rows 里每项是 dict，skipped 是因为实验室不够而没能
    排上的计划项数量。
    """
    plan = LAB_PLAN[: len(labs)]
    skipped = len(LAB_PLAN) - len(plan)

    # 每天各排几条。走完 PER_DAY 就从头再来，保证总数与 sum(PER_DAY) 一致。
    day_slots = []
    for offset, count in enumerate(PER_DAY):
        day_slots.extend([offset] * count)
    # 按实验室权重从高到低依次消耗"当天名额"，这样霸榜的实验室天天都有单，
    # 冷门实验室集中在少数几天，趋势和排行看起来才像真的。
    day_slots.sort()

    owners = list(owner_ids)
    rows = []
    cursor = 0
    for lab_index, (approved, pending, rejected, canceled) in enumerate(plan):
        lab = labs[lab_index]
        statuses = [1] * approved + [0] * pending + [2] * rejected + [3] * canceled
        # 同一实验室内按天分桶，避免同一天同一时段撞车（见下面 slot 的取法）
        for k, status in enumerate(statuses):
            create_offset = day_slots[cursor % len(day_slots)]
            cursor += 1
            # 预约的是**将来**的日子：create_time 最晚是今天，date 从明天起，
            # 所以"下单时间早于使用日期"这个常识关系永远成立。
            target = today + timedelta(days=1 + (k % 7))
            start, end = SLOTS[(k // 7) % len(SLOTS)]
            owner = user_id if user_id is not None else owners[k % len(owners)]
            rows.append(
                {
                    "user_id": owner,
                    "lab_id": lab.id,
                    "lab_name": lab.name,
                    "equipment_id": None,  # 空 = 预约实验室（不是约设备）
                    "date": target.strftime("%Y-%m-%d"),
                    "start_time": start,
                    "end_time": end,
                    "remark": f"{REMARKS[k % len(REMARKS)]} | {MARKER}",
                    "status": status,
                    # create_time 是 naive 本地时间，与 Base.create_time 的
                    # default=datetime.now 同源。换 UTC 会让整个趋势窗口错位一天。
                    "create_time": datetime.combine(
                        today - timedelta(days=6 - create_offset),
                        time(9 + (k % 9), (k * 7) % 60),
                    ),
                }
            )
    return rows, skipped


def table_counts(db):
    return {
        "users": db.query(User).count(),
        "labs": db.query(Lab).count(),
        "equipments": db.query(Equipment).count(),
        "reservation": db.query(Reservation).count(),
        "reservation(本脚本标记)": db.query(Reservation)
        .filter(Reservation.remark.like(ROLLBACK_LIKE))
        .count(),
    }


def show_counts(title, counts):
    print(f"\n{title}")
    for key, value in counts.items():
        print(f"    {key:<26} {value}")


def project_charts(db, rows, today, reset):
    """把"库里已有的"和"将要写入的"合起来，推算首页两个图最终会显示成什么。

    光看"我要写 30 行"判断不出图表好不好看，也判断不出会不会某个状态段是 0。
    预演的意义就在这里：先看到结果，再决定要不要写。
    """
    # remark 为 NULL 的行 NOT LIKE 的结果也是 NULL（不是 True），会被过滤掉，
    # 所以必须显式带上 is_(None) 这一支，否则统计口径会凭空少掉一批行。
    not_marker = or_(Reservation.remark.is_(None), ~Reservation.remark.like(ROLLBACK_LIKE))

    status_q = db.query(Reservation.status, func.count(Reservation.id))
    if reset:
        status_q = status_q.filter(not_marker)
    status_counts = dict(status_q.group_by(Reservation.status).all())

    start_day = today - timedelta(days=6)
    start_dt = datetime.combine(start_day, time.min)
    trend_q = db.query(func.date(Reservation.create_time), func.count(Reservation.id)).filter(
        Reservation.create_time >= start_dt
    )
    if reset:
        trend_q = trend_q.filter(not_marker)
    # func.date() 在 MySQL 下可能返回 date 也可能返回 str，统一转成 YYYY-MM-DD 当 key
    trend = {str(day): count for day, count in trend_q.group_by(
        func.date(Reservation.create_time)).all()}

    for row in rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
        key = row["create_time"].date().strftime("%Y-%m-%d")
        trend[key] = trend.get(key, 0) + 1

    return status_counts, trend, start_day


def show_projection(status_counts, trend, start_day):
    total = sum(status_counts.values())
    print("\n写入后，首页两个图会显示成：")
    if total == 0:
        print("    预约状态分布  {卡片走空态：暂无预约记录}")
    else:
        parts = []
        for status in (0, 1, 2, 3):
            count = status_counts.get(status, 0)
            parts.append(f"{STATUS_NAME[status]} {count}({round(count / total * 100)}%)")
        print(f"    预约状态分布  {'，'.join(parts)}   合计 {total} 条")
        zero = [STATUS_NAME[s] for s in (0, 1, 2, 3) if status_counts.get(s, 0) == 0]
        if zero:
            print(f"                  注意：{'、'.join(zero)} 是 0，条上那一段会看不见（属正常）")

    total7 = sum(trend.get((start_day + timedelta(days=i)).strftime("%Y-%m-%d"), 0) for i in range(7))
    if total7 == 0:
        print("    近 7 天趋势    {卡片走空态：近 7 天还没有新预约}")
    else:
        bars = []
        for i in range(7):
            day = (start_day + timedelta(days=i)).strftime("%Y-%m-%d")
            bars.append(f"{day[5:]} {trend.get(day, 0)}")
        print(f"    近 7 天趋势    {'  '.join(bars)}   合计 {total7} 条")


def main():
    parser = argparse.ArgumentParser(description="生成演示用的预约数据（默认只预演）")
    parser.add_argument("--apply", action="store_true", help="真正写库；不加则只预演")
    parser.add_argument(
        "--reset",
        action="store_true",
        help=f"先删除 remark 匹配 {ROLLBACK_LIKE} 的行（只删本脚本的产物）",
    )
    parser.add_argument("--user-id", type=int, default=None, help="把演示行全挂在这个用户 id 下")
    args = parser.parse_args()

    today = datetime.now().date()
    db = SessionLocal()
    try:
        before = table_counts(db)
        show_counts("写库前，四张表的行数：", before)

        labs = db.query(Lab).order_by(Lab.id).all()
        users = db.query(User).all()
        if not labs:
            print("\n中止：库里一个实验室都没有。演示预约必须挂在真实实验室上。")
            return 1
        if not users:
            print(
                "\n中止：库里一个用户都没有。\n"
                "这个脚本**刻意不创建用户**——公开仓库里不能出现硬编码的默认账号。\n"
                "请先用系统正常注册一个账号，再回来跑这个脚本。"
            )
            return 1
        if args.user_id is not None and args.user_id not in {u.id for u in users}:
            print(f"\n中止：指定的 --user-id {args.user_id} 在库里不存在。")
            return 1

        # 演示预约只挂学生。全库只有管理员时退回挂管理员——那时也别无选择，
        # 而且管理员的统计口径本来就是全库，能不能看到演示数据不受归属影响。
        owner_ids = [u.id for u in users if u.role != "admin"] or [u.id for u in users]
        rows, skipped = build_rows(labs, owner_ids, today, args.user_id)

        # 写库前的自查：rows 的字段必须和模型对得上。
        # 少了这一道，字段写错要等到真正 INSERT 的那一刻才由 SQLAlchemy 抛 TypeError——
        # 那个报错发生在写库路径上，和"数据本身有问题"很难区分。这里提前拦掉。
        unexpected = set(rows[0]) - set(MODEL_FIELDS) - set(DISPLAY_FIELDS)
        if unexpected:
            print(f"\n中止：rows 里有模型不认识的字段 {sorted(unexpected)}，脚本自身有问题。")
            return 1

        print(f"\n将要写入 {len(rows)} 行预约：")
        print(f"    日期窗口     create_time 铺在 {today - timedelta(days=6)} ~ {today}")
        print("    每天条数     " + "  ".join(f"{c}" for c in PER_DAY))
        by_status = {}
        for row in rows:
            by_status[row["status"]] = by_status.get(row["status"], 0) + 1
        print(
            "    状态分布     "
            + "，".join(f"{STATUS_NAME[s]} {by_status.get(s, 0)}" for s in (0, 1, 2, 3))
        )
        ranked = {}
        for row in rows:
            if row["status"] in (0, 1):
                ranked[row["lab_name"]] = ranked.get(row["lab_name"], 0) + 1
        print("    进排行榜     " + "，".join(f"{n} {c}" for n, c in ranked.items()))
        by_owner = {}
        for row in rows:
            by_owner[row["user_id"]] = by_owner.get(row["user_id"], 0) + 1
        print("    归属账号     " + "，".join(f"用户#{u} {c} 条" for u, c in by_owner.items()))
        if skipped:
            print(f"    注意         实验室只有 {len(labs)} 个，有 {skipped} 组计划没能排上")
        print("\n    前 3 行样例：")
        for row in rows[:3]:
            print(
                f"      {row['lab_name']} {row['date']} {row['start_time']}-{row['end_time']} "
                f"status={row['status']}({STATUS_NAME[row['status']]}) user={row['user_id']}"
            )

        status_counts, trend, start_day = project_charts(db, rows, today, args.reset)
        show_projection(status_counts, trend, start_day)

        print(f"\n回滚 SQL（只删本脚本写进去的行）：")
        print(f"    DELETE FROM reservation WHERE remark LIKE '{ROLLBACK_LIKE}';")

        if args.reset:
            if args.apply:
                deleted = (
                    db.query(Reservation)
                    .filter(Reservation.remark.like(ROLLBACK_LIKE))
                    .delete(synchronize_session=False)
                )
                db.commit()
                print(f"\n--reset：已删除 {deleted} 行本脚本以前写的预约。")
            else:
                print(
                    f"\n--reset：预演模式下不执行。真正写入时会先删除 "
                    f"{before['reservation(本脚本标记)']} 行。"
                )

        if not args.apply:
            print("\n这是预演，什么都没有写。确认无误后加 --apply 再跑一次。")
            return 0

        db.add_all(Reservation(**{k: row[k] for k in MODEL_FIELDS}) for row in rows)
        db.commit()

        after = table_counts(db)
        show_counts("写库后，四张表的行数：", after)

        # 用行数自证，不用"脚本说它成功了"。加了 --reset 时基数会变，
        # 所以比的是"本脚本标记行"的增量，而不是 reservation 总数的增量。
        gained = after["reservation(本脚本标记)"] - (
            0 if args.reset else before["reservation(本脚本标记)"]
        )
        print(f"\n本脚本标记行净增 {gained} 行（预期 {len(rows)}）。")
        if gained != len(rows):
            print("!! 净增与预期不符，请人工核对，不要当成成功。")
            return 1
        for key in ("users", "labs", "equipments"):
            if after[key] != before[key]:
                print(f"!! {key} 的行数被改动了（{before[key]} -> {after[key]}），这不该发生。")
                return 1
        print("users / labs / equipments 行数未变，确认没有越界写入。")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
