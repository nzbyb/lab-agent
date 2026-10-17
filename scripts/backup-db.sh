#!/usr/bin/env bash
# ============================================================
# 每天导出一次 MySQL，保留最近 KEEP_DAYS 天。
#
# 用法（在仓库根目录、也就是 docker-compose.yml 所在的地方跑）：
#   ./scripts/backup-db.sh                 # 默认保留 7 天
#   KEEP_DAYS=14 ./scripts/backup-db.sh    # 想留更久
#
# 放在哪儿：仓库根的 backups/（已写进 .gitignore，绝不会进仓库）。
# 文件名带日期时间，例如 lab_agent-20261017-032000.sql.gz。
#
# 为什么密码不出现在这个脚本里：mysqldump 跑在 mysql 容器**里面**，
# 直接从容器自己的环境变量 $MYSQL_ROOT_PASSWORD 取。所以脚本本身、命令行历史、
# 进程列表里都不会有密码，这个文件也可以放心提交到公开仓库。
#
# ⚠️ 备份存在同一台服务器上，只能防"误删库 / 表写坏了"这类事故，
#    防不了整台机器没了。所以 README 里建议每周手动下载一份到自己的电脑。
#
# 恢复办法（把 <文件> 换成实际文件名，**先把库清空再导入**）：
#   gunzip < backups/<文件> | docker compose exec -T mysql sh -c \
#     'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --default-character-set=utf8mb4 lab_agent'
# ============================================================

set -euo pipefail

# 脚本放在 scripts/ 下，所以仓库根是它的上一级。cd 过去是为了
# `docker compose` 能找到 docker-compose.yml（它只认当前目录）。
cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-$PWD/backups}"
KEEP_DAYS="${KEEP_DAYS:-7}"
DB_NAME="${DB_NAME:-lab_agent}"

mkdir -p "$BACKUP_DIR"

timestamp="$(date +%Y%m%d-%H%M%S)"
out="$BACKUP_DIR/lab_agent-$timestamp.sql.gz"
part="$out.part"

# 先写 .part、成功之后再改名。中途失败（磁盘满、容器被停）时，
# 留下的半个文件不会冒充"最近一份备份"，下次清理也不会把它当完整备份留着。
#
# set -o pipefail 是关键：没有它，mysqldump 失败会被 gzip 的成功退出码盖住，
# 于是"备份失败"看起来像"备份成功"，只是文件特别小——这是备份脚本最经典的坑。
if ! docker compose exec -T mysql sh -c \
    "exec mysqldump -uroot -p\"\$MYSQL_ROOT_PASSWORD\" \
      --single-transaction --quick --no-tablespaces \
      --routines --events --triggers \
      --default-character-set=utf8mb4 $DB_NAME" \
    | gzip -9 > "$part"; then
    rm -f "$part"
    echo "备份失败：mysqldump 或 gzip 返回了非零退出码" >&2
    exit 1
fi

# 空库导出来只有几百字节。小于 1KB 基本可以认定不是一份能用的备份。
size=$(wc -c < "$part")
if [ "$size" -lt 1024 ]; then
    rm -f "$part"
    echo "备份失败：导出文件只有 $size 字节，明显不对" >&2
    exit 1
fi

# 再确认一遍 gzip 能完整解压（截断的 gzip 文件末尾会报错）
if ! gzip -t "$part" 2>/dev/null; then
    rm -f "$part"
    echo "备份失败：gzip 校验不通过，文件不完整" >&2
    exit 1
fi

mv "$part" "$out"

# 只清理本脚本自己生成的文件，不碰目录里别的东西
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'lab_agent-*.sql.gz' \
    -mtime "+$KEEP_DAYS" -delete

count=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'lab_agent-*.sql.gz' | wc -l)
echo "备份完成：$out（$((size / 1024)) KB），当前保留 $count 份，超过 $KEEP_DAYS 天的已清理"
