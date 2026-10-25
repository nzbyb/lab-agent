#!/usr/bin/env bash
# ============================================================
# 从 backup-db.sh 生成的 .sql.gz 恢复到一个**测试库**，用来做恢复演练。
#
# 用法（仓库根目录，docker compose 的 mysql 容器在跑）：
#   ./scripts/restore-db.sh backups/lab_agent-20261017-032015.sql.gz
#
# 默认恢复到 lab_agent_restore_test。这个名字是故意的：
#   - 演练不该碰正式库；
#   - 库名必须以 _restore_test 结尾，脚本才肯往下走，否则直接拒绝。
# 想在演练里对比行数，脚本最后会把几张关键表的 COUNT(*) 打出来。
#
# ⚠️ 恢复正式库（灾难恢复）：
#   ALLOW_PROD_RESTORE=yes ./scripts/restore-db.sh backups/xxx.sql.gz lab_agent
# 这会**清空并覆盖**正式库，执行前先停掉后端：
#   docker compose stop backend
# 恢复完再 start。它会要求你手动输入 yes 再继续。
#
# 为什么脚本里没有密码：mysql 客户端跑在 mysql 容器**里面**，
# 从容器自己的 $MYSQL_ROOT_PASSWORD 取，跟 backup-db.sh 同一套做法。
# ============================================================

set -euo pipefail

cd "$(dirname "$0")/.."

if [ $# -lt 1 ]; then
    echo "用法：$0 <备份文件.sql.gz> [目标库名，默认 lab_agent_restore_test]" >&2
    exit 2
fi

dump_file="$1"
target_db="${2:-lab_agent_restore_test}"

if [ ! -f "$dump_file" ]; then
    echo "找不到备份文件：$dump_file" >&2
    exit 1
fi

# 先验 gzip 完整性。截断的文件在导入时会报错，但可能已经写进去一半数据，
# 所以要在动数据库之前就拦住。
if ! gzip -t "$dump_file" 2>/dev/null; then
    echo "备份文件 gzip 校验不通过，可能已损坏或不完整：$dump_file" >&2
    exit 1
fi

# 第二道保险丝：默认只允许恢复到 *_restore_test。
# 想恢复正式库必须显式设置 ALLOW_PROD_RESTORE=yes。
case "$target_db" in
    *_restore_test) ;;
    *)
        if [ "${ALLOW_PROD_RESTORE:-}" != "yes" ]; then
            echo "拒绝恢复到 '$target_db'：目标库不是 *_restore_test。" >&2
            echo "演练请用默认库名；确实要恢复正式库时加 ALLOW_PROD_RESTORE=yes。" >&2
            exit 1
        fi
        ;;
esac

if [ "${ALLOW_PROD_RESTORE:-}" = "yes" ]; then
    echo "⚠️  即将覆盖正式库 '$target_db'，库里的现有数据会全部丢失。"
    read -r -p "确认输入 yes 继续：" answer
    if [ "$answer" != "yes" ]; then
        echo "已取消"
        exit 1
    fi
fi

echo "==> 准备目标库 $target_db"
docker compose exec -T mysql sh -c \
    'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --default-character-set=utf8mb4 \
      -e "CREATE DATABASE IF NOT EXISTS \`$0\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"' \
    "$target_db"

echo "==> 导入 $dump_file"
# --init-command 不用；直接让 mysql 客户端读 stdin。
# pipefail 保证解压失败不会被 mysql 的退出码盖住。
gunzip -c "$dump_file" | docker compose exec -T mysql sh -c \
    'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --default-character-set=utf8mb4 "$0"' \
    "$target_db"

echo "==> 导入完成，核对关键表行数"
docker compose exec -T mysql sh -c \
    'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --default-character-set=utf8mb4 "$0" -e "
      SELECT 'labs' AS table_name, COUNT(*) AS rows_count FROM labs
      UNION ALL SELECT 'equipments', COUNT(*) FROM equipments
      UNION ALL SELECT 'users', COUNT(*) FROM users
      UNION ALL SELECT 'reservation', COUNT(*) FROM reservation
      UNION ALL SELECT 'notifications', COUNT(*) FROM notifications;"' \
    "$target_db"

echo "==> 恢复演练完成：$target_db"
echo "    确认行数和正式库接近后，可以删掉测试库："
echo "    docker compose exec -T mysql sh -c 'exec mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -e \"DROP DATABASE $target_db\"'"
