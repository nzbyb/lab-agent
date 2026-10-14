#!/usr/bin/env bash
# ============================================================
# 一键初始化：把刚起来的空 Docker 环境填成能用的演示系统
#
#   bash scripts/init-demo.sh --username zhangsan
#
# 它按顺序做四件事：
#   1. 往库里灌 backend/demo_data.sql —— 8 间实验室 + 32 台设备
#   2. 注册一个账号（走真实的注册接口，密码是后端真哈希过的）
#   3. 可选 --admin：把这个账号提成管理员，好看到管理端
#   4. 可选（默认做）：跑 seed_demo_data.py 造一批演示预约
#
# ------------------------------------------------------------
# 为什么账号密码要你自己传，而不是给个默认的：
#
# 这个仓库是**公开的**。脚本里写死任何 "默认账号 / 默认密码"，
# 就等于往公开仓库里放了一份公开凭据。
# 同一套规矩仓库里已经立过两次：demo_data.sql 刻意只插实验室和设备、
# 不建用户；seed_demo_data.py 的注释里也写明"绝不新建用户"。
# 这里保持一致。
#
# 密码不传的话会**交互式问你**（输入不回显），这样也不会留在
# shell 历史记录里。
# ------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")/.."   # 切到仓库根目录，后面所有相对路径都以它为准

COMPOSE_URL="http://localhost:8080"

USERNAME=""
PASSWORD=""
DISPLAY_NAME=""
MAKE_ADMIN=0
SEED_RESERVATIONS=1

usage() {
  cat <<'EOF'
用法：
  bash scripts/init-demo.sh --username <账号名> [选项]

必填：
  --username <名字>     要注册的账号名

常用选项：
  --password <密码>     不传的话会交互式问你（推荐，不会进 shell 历史）
  --name <显示名>       界面上显示的名字，默认跟账号名一样
  --admin               把这个账号提成管理员（能看到管理端）
  --no-reservations     不生成演示预约数据，只留实验室和设备
  -h, --help            看这份说明

例子：
  bash scripts/init-demo.sh --username zhangsan --admin
  bash scripts/init-demo.sh --username lisi --password 'xxx' --no-reservations

跑之前：Docker Desktop 要在跑，且 docker compose up -d 已经起过一套。
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --username)        USERNAME="${2:-}"; shift 2 ;;
    --password)        PASSWORD="${2:-}"; shift 2 ;;
    --name)            DISPLAY_NAME="${2:-}"; shift 2 ;;
    --admin)           MAKE_ADMIN=1; shift ;;
    --no-reservations) SEED_RESERVATIONS=0; shift ;;
    -h|--help)         usage; exit 0 ;;
    *) echo "不认识的参数：$1" >&2; echo; usage; exit 2 ;;
  esac
done

if [ -z "$USERNAME" ]; then
  echo "错误：必须给 --username。" >&2
  echo >&2
  usage >&2
  exit 2
fi

# 账号名只允许字母、数字、下划线、点、减号。
#
# 不是洁癖：这个名字要拼进 JSON（注册请求体）和 SQL（提管理员那条 UPDATE），
# 带引号会把两边都拼坏。白名单比黑名单省事，也不会漏。
#
# 想用别的字符（比如中文名）就直接在网页上注册——那条路走后端自己的校验，
# 不经过这个脚本的字符串拼接。
case "$USERNAME" in
  *[!A-Za-z0-9_.-]*)
    echo "账号名只能用英文字母、数字、下划线、点、减号。" >&2
    echo "想用别的字符请直接在网页 http://localhost:8080/register 上注册。" >&2
    exit 2
    ;;
esac
if [ "${#USERNAME}" -gt 50 ]; then
  echo "账号名最长 50 个字符（后端 schema 就是这么卡的）。" >&2
  exit 2
fi

# ------------------------------------------------------------
# 万恶之源：所有 docker compose exec 都必须带上 </dev/null
#
# docker compose exec 默认会把**脚本自己的 stdin** 接进容器。不挡住的话，
# 后面几个取行数的 exec 会抢先把 stdin 读空，轮到 read 问密码时只剩 EOF。
# 表现是：提示符打出来了，然后脚本一声不吭地退出（read 遇 EOF 返回非零，
# 配上 set -e 就是静默中止）——非常难查。
#
# 唯一需要 stdin 的那一条是灌 SQL，它自己显式 < backend/demo_data.sql。
# 下面每个 exec 都写了 </dev/null，改这个脚本时请保持。
# ------------------------------------------------------------
MYSQL() {
  # --default-character-set=utf8mb4 不能省：不带的话连接按 latin1 走，
  # 收尾那行 CONCAT 出来的中文会变成乱码。
  docker compose exec -T mysql sh -c \
    "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" --default-character-set=utf8mb4 $1" \
    </dev/null 2>/dev/null
}
# 注意：传进来的 SQL 里如果有字符串字面量，只能用**单引号**。
# MYSQL 已经把整条 SQL 包在一对双引号里了，再写双引号会把外层闭合掉，
# 结果就是 mysql 收到一堆莫名其妙的参数，然后把用法帮助喷满屏。
MYSQL_Q() { MYSQL "-N -B lab_agent -e \"$1\""; }

# ------------------------------------------------------------
# 0. 让 docker 命令能被找到
#
# Windows 上 Docker Desktop 是**用户级安装**，bin 目录在注册表里，
# 但已经开着的终端继承的是安装之前那份旧 PATH —— 表现成
# 「无法将"docker"项识别为 cmdlet...」。
# 这里自己找一遍，省得你去手改环境变量。
# ------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  for cand in \
    "$HOME/AppData/Local/Programs/DockerDesktop/resources/bin" \
    "${LOCALAPPDATA:-}/Programs/DockerDesktop/resources/bin" \
    "/c/Program Files/Docker/Docker/resources/bin" \
    "/Applications/Docker.app/Contents/Resources/bin" \
    "$HOME/.docker/bin"
  do
    [ -n "$cand" ] || continue
    # Git Bash 认不出 "C:\..." 这种 Windows 形式的 PATH 条目：
    # [ -x ] 能测通，但加进 PATH 之后 command -v 还是找不到。
    # 有 cygpath 就先转成 /c/... 形式，这一步不能省
    # —— 不转的话 $LOCALAPPDATA 那条会假装匹配成功然后把 PATH 弄坏。
    if command -v cygpath >/dev/null 2>&1; then
      cand="$(cygpath -u "$cand" 2>/dev/null || printf '%s' "$cand")"
    fi
    if [ -x "$cand/docker" ] || [ -x "$cand/docker.exe" ]; then
      PATH="$cand:$PATH"
      export PATH
      break
    fi
  done
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "找不到 docker 命令。请确认 Docker Desktop 已经装好并正在运行。" >&2
  exit 1
fi

# ------------------------------------------------------------
# 1. 确认这套服务真的起来了
# ------------------------------------------------------------
echo "==> 检查服务状态"
if ! docker compose ps --format '{{.Service}} {{.Status}}' 2>/dev/null | grep -q '^mysql .*healthy'; then
  echo "MySQL 容器没在跑（或者还没到 healthy）。先在仓库根目录执行：" >&2
  echo "    docker compose up -d" >&2
  exit 1
fi
if ! curl -sf -o /dev/null "$COMPOSE_URL/"; then
  echo "前端 $COMPOSE_URL 打不开。检查一下：docker compose ps" >&2
  exit 1
fi
echo "    MySQL healthy，前端可访问。"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ------------------------------------------------------------
# 2. 灌实验室和设备
#
# demo_data.sql 开头是 DELETE FROM equipments; DELETE FROM labs;
# 这是**故意的**（可重复执行）。但如果库里已经有预约记录，外键会挡住删除。
# 真遇到那种情况，先把预约清掉，或者干脆 docker compose down -v 重来。
# ------------------------------------------------------------
echo "==> 灌实验室与设备数据（backend/demo_data.sql）"
if ! docker compose exec -T mysql sh -c \
      'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --default-character-set=utf8mb4 lab_agent' \
      < backend/demo_data.sql 2>"$TMP/sql.err"; then
  echo >&2
  echo "############################################################" >&2
  echo "#  灌数据失败 —— 脚本在这里停住了，后面几步都没有执行。     #" >&2
  echo "############################################################" >&2
  echo >&2
  grep -v "Using a password on the command line" "$TMP/sql.err" >&2 || true
  echo >&2

  # 只有真撞上外键才给"先清预约"那条建议。不分青红皂白地一律提示去删预约，
  # 在别的原因失败时（比如 mysql 容器压根没起来）会把人引到一条完全无关的路上。
  # MySQL 命令行报外键错的原话是：
  #   ERROR 1451 (23000) at line N: Cannot delete or update a parent row: a foreign key constraint fails (...)
  # 三个特征串任中一个即可（1451 是外键约束的专用错误码）。
  if grep -qi "foreign key\|Cannot delete or update a parent row\|ERROR 1451" "$TMP/sql.err"; then
    BLOCKING="$(MYSQL_Q 'SELECT COUNT(*) FROM reservation;' | tr -d '\r')"
    echo "------------------------------------------------------------" >&2
    echo "原因：外键挡住了。demo_data.sql 一上来就 DELETE FROM labs，" >&2
    echo "而库里还有 ${BLOCKING:-?} 条预约记录指着这些实验室，MySQL 不让删。" >&2
    echo >&2
    echo "**这个脚本目前不能直接重复跑**——不是坏了，是需要你先清一次。" >&2
    echo >&2
    echo "三选一：" >&2
    echo "  1) 清掉预约再重跑（账号、实验室、设备都不动）：" >&2
    echo "     docker compose exec -T mysql sh -c 'mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" lab_agent -e \"DELETE FROM reservation;\"'" >&2
    echo "  2) 连数据卷一起重来（账号和预约全没，等于全新安装）：" >&2
    echo "     docker compose down -v && docker compose up -d" >&2
    echo "  3) 你只是想要一批演示预约？那不用跑这个脚本，直接：" >&2
    echo "     docker compose exec -T backend python scripts/seed_demo_data.py --reset --apply" >&2
    echo "------------------------------------------------------------" >&2
  fi
  exit 1
fi

LABS="$(MYSQL_Q 'SELECT COUNT(*) FROM labs;' | tr -d '\r')"
EQUIPS="$(MYSQL_Q 'SELECT COUNT(*) FROM equipments;' | tr -d '\r')"
echo "    灌完：实验室 $LABS 间，设备 $EQUIPS 台。"

# ------------------------------------------------------------
# 3. 注册账号
# ------------------------------------------------------------
if [ -z "$PASSWORD" ]; then
  printf '请输入 %s 的密码（输入时不显示）：' "$USERNAME"
  # read 遇到 EOF 会返回非零，set -e 下会静默中止。显式处理，给个能看懂的提示。
  if ! read -r -s PASSWORD; then
    echo
    echo "没能读到密码（脚本的输入被关掉了）。改用 --password 直接传。" >&2
    exit 1
  fi
  echo
  printf '再输一遍确认：'
  if ! read -r -s PASSWORD2; then
    echo
    echo "没能读到确认密码。" >&2
    exit 1
  fi
  echo
  if [ "$PASSWORD" != "${PASSWORD2:-}" ]; then
    echo "两次输入不一致，中止。" >&2
    exit 1
  fi
fi
if [ -z "$PASSWORD" ]; then
  echo "密码不能为空。" >&2
  exit 1
fi

if [ -z "$DISPLAY_NAME" ]; then
  DISPLAY_NAME="$USERNAME"
fi

echo "==> 注册账号 $USERNAME"
# 请求体写成文件再发，不经 shell —— 中文字段值走命令行会被 Windows 的
# 代码页转成 GBK，后端按 UTF-8 解析就报"解析请求体失败"。
printf '{"username":"%s","password":"%s","name":"%s"}' \
  "$USERNAME" "$PASSWORD" "$DISPLAY_NAME" > "$TMP/reg.json"

REG_HTTP=$(curl -s -o "$TMP/reg.out" -w '%{http_code}' \
  -X POST "$COMPOSE_URL/api/auth/register" \
  -H 'Content-Type: application/json' \
  --data-binary @"$TMP/reg.json" </dev/null || echo 000)

# 后端把**业务错误也包在 HTTP 200 里**返回，body 长这样：
#     {"code":400,"message":"账号已存在"}
# 所以只看 HTTP 状态码会把"账号已存在"当成注册成功。必须连 body 里的 code 一起看。
# （这个坑不修的话，密码太弱之类的真失败也会被说成"注册成功"，
#   然后在登录那步报一个牛头不对马嘴的错。）
REG_CODE=$(grep -o '"code":[0-9]*' "$TMP/reg.out" 2>/dev/null | head -1 | cut -d: -f2 || true)
REG_MSG=$(grep -o '"message":"[^"]*"' "$TMP/reg.out" 2>/dev/null | head -1 | cut -d'"' -f4 || true)

if [ "$REG_HTTP" != "200" ]; then
  echo "    注册请求失败了（HTTP $REG_HTTP）：" >&2
  cat "$TMP/reg.out" >&2
  echo >&2
  exit 1
fi

if [ "$REG_CODE" = "200" ]; then
  echo "    注册成功。"
else
  # 注册被后端拒了，最常见的就是"账号已存在"——这脚本本来就该能重复跑。
  # 不在这儿判死：下一步的登录才是"账号真能用"的凭据。
  echo "    注册没成功（后端说：${REG_MSG:-读不出原因}），继续往下走登录验证。"
fi

# ------------------------------------------------------------
# 4. 登录，拿 token 和用户 id
#    这一步同时是**密码是否正确的证明** —— 注册接口不回显任何东西，
#    只有登录成功才说明账号真的可用。
# ------------------------------------------------------------
echo "==> 登录验证"
printf '{"username":"%s","password":"%s"}' "$USERNAME" "$PASSWORD" > "$TMP/login.json"

curl -s -o "$TMP/login.out" -X POST "$COMPOSE_URL/api/auth/login" \
  -H 'Content-Type: application/json' \
  --data-binary @"$TMP/login.json" </dev/null

# 用 grep 抠字段，不依赖 jq（Windows 上不一定装）
TOKEN=$(grep -o '"token":"[^"]*"' "$TMP/login.out" | head -1 | cut -d'"' -f4 || true)
USER_ID=$(grep -o '"id":[0-9]*' "$TMP/login.out" | head -1 | cut -d: -f2 || true)

if [ -z "$TOKEN" ] || [ -z "$USER_ID" ]; then
  echo "登录失败，账号没能用起来。后端原话：" >&2
  cat "$TMP/login.out" >&2
  echo >&2
  echo "常见原因：这个账号名已经存在，但密码跟你现在给的不一样。" >&2
  echo "换一个账号名，或者用原来的密码。" >&2
  exit 1
fi
echo "    登录成功，用户 id = $USER_ID。"

# 顺手证明这个 token 真能拿到数据（不是只看登录接口自说自话）
LIST_HTTP=$(curl -s -o "$TMP/labs.out" -w '%{http_code}' \
  "$COMPOSE_URL/api/lab/list" -H "Authorization: Bearer $TOKEN" </dev/null || echo 000)
if [ "$LIST_HTTP" = "200" ]; then
  echo "    带 token 取实验室列表：HTTP 200 ✓"
else
  echo "    带 token 取列表返回 HTTP $LIST_HTTP（不致命，但值得看一眼）" >&2
fi

# ------------------------------------------------------------
# 5. 可选：提成管理员
# ------------------------------------------------------------
if [ "$MAKE_ADMIN" = "1" ]; then
  echo "==> 把 $USERNAME 提成管理员"
  MYSQL "lab_agent -e \"UPDATE users SET role='admin' WHERE username='$USERNAME';\"" >/dev/null
  ROLE="$(MYSQL_Q "SELECT role FROM users WHERE username='$USERNAME';" | tr -d '\r')"
  echo "    现在角色是：$ROLE"
  echo "    ⚠️ 已经登录的话要重新登录一次，前端缓存的角色还是旧的。"
fi

# ------------------------------------------------------------
# 6. 可选：造演示预约
# ------------------------------------------------------------
if [ "$SEED_RESERVATIONS" = "1" ]; then
  echo "==> 生成演示预约数据"
  docker compose exec -T backend python scripts/seed_demo_data.py \
    --reset --apply --user-id "$USER_ID" </dev/null
else
  echo "==> 按你的要求跳过演示预约数据"
fi

# ------------------------------------------------------------
# 7. 收尾：最终状态以行数为准打出来
#    （不信任何一步自己说的"完成"）
# ------------------------------------------------------------
echo
echo "==================== 最终状态 ===================="
MYSQL_Q "SELECT CONCAT('实验室 ',(SELECT COUNT(*) FROM labs),' 间 / 设备 ',(SELECT COUNT(*) FROM equipments),' 台 / 账号 ',(SELECT COUNT(*) FROM users),' 个 / 预约 ',(SELECT COUNT(*) FROM reservation),' 条');"
echo "=================================================="
echo
echo "可以开 http://localhost:8080 登录了。"
echo "  账号：$USERNAME"
if [ "$MAKE_ADMIN" = "1" ]; then
  echo "  角色：管理员（管理端也能进）"
else
  echo "  角色：学生"
fi
echo
echo "想从零重来：docker compose down -v && docker compose up -d && bash scripts/init-demo.sh ..."
