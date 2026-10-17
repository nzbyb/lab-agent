<img src="docs/logo.svg" width="72" height="72" alt="">

# 智能实验室预约系统

> A lab and equipment booking system with an LLM assistant that queries the database and places bookings on the user's behalf.

学生预约实验室、借用设备，管理员维护基础数据、审核预约。站内带一个 AI 助手（叫「小田」），它能真的去查空闲时段、查设备、替用户下单，而不是只会闲聊。

**仓库里没有任何演示账号和密码。** 想跑起来请自己注册一个——`scripts/init-demo.sh` 会引导你注册，密码当场由你输入，不进仓库。

---

## 功能

**学生**

- 注册 / 登录（JWT），改资料、改密码
- 按关键词搜实验室、看设备清单
- 预约实验室：选日期和时段，时间冲突会被拦下
- 借用设备：预约设备时要一并选所属实验室；同一时段约了整间实验室，这间里的设备就都约不了，反过来也一样（只有同间实验室的两台不同设备互不影响）
- 我的预约：查看、取消（只有待审核的能取消）。待审核的预约过了时段还没人审核，后台每 60 秒扫一次，自动置为已取消；已通过、已拒绝的不在这个扫描范围里
- AI 助手：查规章制度、查某天某实验室的空闲时段、查设备，也能直接下单；对话历史存在后端，换台设备登录还能接着聊

**管理员**

- 实验室、设备的增删改查
- 审核预约
- 用户管理，含**重置他人密码**（不需要知道对方原密码；重置后那个人所有设备立刻掉线）

## 技术栈

| 层 | 用了什么 |
| --- | --- |
| 前端 | Vue 3（`<script setup>`）、Vite、Pinia、Vue Router、Element Plus、ECharts、axios、marked + DOMPurify |
| 后端 | FastAPI、SQLAlchemy 2.0、Pydantic v2、PyMySQL |
| 数据库 | MySQL；表结构由 Alembic 管（迁移在 `backend/migrations/`，服务启动时自动升到最新）。实验室开放时间分周中、周末两档，同一天用哪档由 `lab_service.resolve_open_hours` 一处判定 |
| 鉴权 | JWT（PyJWT）+ bcrypt |
| AI | LangGraph 编排工具调用、langchain-openai / langchain-core、ChromaDB + sentence-transformers + `BAAI/bge-small-zh-v1.5` 做本地向量检索 |
| 限流 | slowapi；计数默认存 Redis（Redis 不可用时退回进程内存，不会让接口报错） |

---

## 跑起来

两条路。**只想看看界面长什么样**走第一条，本机不用装 Python、Node、MySQL。**要改代码**走后面，本机跑开发服务，有热重载和断点。

### 用 Docker 起全套

```bash
copy .env.example .env          # macOS / Linux: cp .env.example .env
```

打开刚生成的根目录 `.env`，把这五个填上：

| 变量 | 填什么 |
| --- | --- |
| `MYSQL_ROOT_PASSWORD` | 随便定一个，只给这个容器用 |
| `JWT_SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL` | 任何 OpenAI 兼容接口，要有 `/chat/completions` |

`TZ`、`CORS_ORIGINS`、`JWT_EXPIRE_HOURS` 都有默认值，不用动。这五个少一个，`docker compose up` 会**直接报错退出**，不会拿空值硬起——`JWT_SECRET_KEY` 照抄 `.env.example` 里的示例值也一样起不来（后端的启动自检会拒绝）。

```bash
docker compose up -d
```

第一次要下基础镜像和一批 Python 依赖。装完 `site-packages` 是 1.8G，其中 CPU 版 torch 自己就占 773M，后端镜像最终 2.6G，慢是正常的。（torch 要是不单独装 CPU 版，pip 会把 CUDA 版一起拽下来，再白多两个多 G。）

> 起来之后是**空库**：表由后端启动时自动建，但一条数据都没有。界面能开，登录不进去。

灌演示数据、顺手注册一个账号：

```bash
bash scripts/init-demo.sh --username 你的账号名 --admin
```

> ⚠️ Windows 上请在 **Git Bash** 里跑这条命令。PowerShell 里的 `bash` 不是 Git Bash（是 WSL 的壳）。

它会问密码（输入不回显，也不留在 shell 历史里），然后灌 8 间实验室 + 32 台设备、注册这个账号、把它提成管理员、再造 30 条演示预约，最后以四张表的行数收尾。

账号密码**必须由你自己传**：仓库是公开的，脚本里带任何默认凭据都等于公开一份。想用中文账号名就直接在 http://localhost:8080/register 上注册（脚本只放行字母数字下划线点减号——它要把这个名字拼进 SQL）。

打开 **http://localhost:8080** 登录。

#### 几个需要知道的

- **端口**：`8080` 前端（所有网卡都能连）；`8001` 后端直连，只绑 `127.0.0.1`，用来 `curl` 看原始响应；`3307` MySQL，只绑 `127.0.0.1`，Navicat 连这个（3306 留给本机自己的 MySQL）。
- **前端容器里的 nginx 自己反代** `/api` 和 `/uploads`，浏览器这边是同源的，所以 `CORS_ORIGINS` 留空是对的。
- **数据在卷里**：`mysql-data`（数据库）和 `uploads`（用户上传的文件）。`docker compose down` 不丢，`down -v` 才清空。
- **知识库索引没挂卷**，容器重建就会重做一遍。第一次要下 92MB 的 embedding 模型，缓存在仓库根的 `./.hf-cache/`（这个目录会保留，不会重复下）。
- **改了代码要重新构建**：`docker compose up -d --build`。跟日志：`docker compose logs -f backend`。
- **限流计数在 Redis 里**（`docker compose` 默认就配好，不用管）：多进程共用一份，**后端重启不清零**。Redis 挂了会退回进程内存继续限流，网站照常可用，`docker compose logs -f backend` 里能看到 `Rate limit storage unreachable`。
- **后端是单进程跑的**（没开 `--workers`）：知识库重建锁这类东西还在进程内存里，多开就各算各的。
- **容器用哪个时区由 `TZ` 决定**，默认 `Asia/Shanghai`。填错的话 AI 答"现在有哪些实验室开放"会整体偏八小时，界面上还看不出来。

想在本机改代码，接着往下看。

### 后端

需要 Python 3.11（开发时用的 3.11.9，仓库里没有声明最低版本）、Node 22.18+ 或 24.12+（见 `frontend/package.json` 的 `engines`）、MySQL（开发时用的 9.7.2，仓库里同样没有固定版本）。

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate                 # macOS / Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                 # macOS / Linux: cp .env.example .env
```

先建库：

```sql
CREATE DATABASE lab_agent DEFAULT CHARSET utf8mb4;
```

然后把 `backend/.env` 填好：

| 变量 | 说明 |
| --- | --- |
| `DATABASE_URL` | `mysql+pymysql://用户名:密码@127.0.0.1:3306/lab_agent?charset=utf8mb4` |
| `JWT_SECRET_KEY` | 至少 32 位随机串：`python -c "import secrets; print(secrets.token_urlsafe(48))"`。填成示例值后端会拒绝启动 |
| `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL` | 任何 OpenAI 兼容接口，需要有 `/chat/completions` |
| `JWT_EXPIRE_HOURS` / `JWT_ALGORITHM` | 默认 24 小时 / HS256，可以不填 |
| `CORS_ORIGINS` | 逗号分隔，本机开发用默认值就行 |
| `AI_MAX_CONCURRENCY` | 同时在跑的 AI 对话上限，默认 3，可以不填 |
| `REDIS_URL` | 限流计数的存储，本机不填就用进程内存；Docker 部署由 compose 自动注入 |

上面五个没有默认值（`DATABASE_URL`、`JWT_SECRET_KEY` 和那三个 LLM 变量），**少一个后端就起不来**——配置是在 import 时就校验的。没有可用的 OpenAI 兼容接口就没法启动，AI 助手不是可选项。

启动，表会自动建出来：

```bash
.venv\Scripts\python -m uvicorn app.main:app --reload
```

> 上面这种 `.venv\Scripts\python` 是 Windows 写法，本节和后面「测试」一节里的命令都是这样。macOS / Linux 上把它换成 `.venv/bin/python`，或者先 `source .venv/bin/activate`，之后直接用裸 `python` 就行。

服务在 `http://127.0.0.1:8000`，接口文档在 `/docs`。

> 第一次启动会去 HuggingFace 下载知识库用的 embedding 模型 `BAAI/bge-small-zh-v1.5`（约 90MB）并建索引。这一步虽然丢在独立线程里跑（不占事件循环），但**启动流程会一直等它跑完**——模型没下完之前端口是不通的，第一次启动别以为卡死了。真失败了也只会在控制台打一段 traceback，**后端照样启动**，代价是 AI 查不到知识库内容。国内网络可以设 `HF_ENDPOINT=https://hf-mirror.com` 走镜像。

空库跑起来没什么可看的，想灌点数据，顺序不能反：

```bash
# 1. 实验室和设备。在 Navicat 之类的工具里整段执行 backend/demo_data.sql
#    ⚠️ 会先清空 labs / equipments 两张表，不可撤销

# 2. 注册一个账号（脚本刻意不建用户——公开仓库里硬编码账号会变成公开的默认凭据）

# 3. 演示用的预约记录。库里没有实验室、或者一个用户都没有，它会直接中止
.venv\Scripts\python scripts/seed_demo_data.py           # 默认只预演、不写库
.venv\Scripts\python scripts/seed_demo_data.py --apply   # 确认无误再加
```

### 前端

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173
```

前端请求打到哪儿，有两种情况：

- 仓库里**没有** `frontend/.env.development`（它被 `.gitignore` 忽略了）。不建这个文件时 `VITE_API_BASE_URL` 是空的，请求发到同源的 5173，由 `vite.config.js` 里的代理把 `/api`、`/uploads` 转发给 `127.0.0.1:8000`。
- 自己建一个 `frontend/.env.development` 写上 `VITE_API_BASE_URL=http://127.0.0.1:8000`，请求就直接打到后端。

两种都要求后端先起来。

打包：`npm run build`，产物在 `frontend/dist`。

> 部署建议让前后端同域：nginx 把 `/api` 反代给后端，静态文件交给 `frontend/dist`。这样浏览器不发跨域请求，`CORS_ORIGINS` 只在前后端分开跑时才有用。
> 这套方案已经落在 `frontend/nginx.conf` 里了（Docker 起前端用的就是它），手动部署可以照抄。
> （顺带一提，也可以让 FastAPI 直接挂载 `dist`，但现在的 `main.py` 只挂载了 `/uploads`，还没做这件事。）

---

## 部署到服务器

本项目已经在一台阿里云 2 核 4G 的机器上真跑起来了（Ubuntu 24.04），下面是照实记下来的过程和坑。

### 机器怎么选

- **内存给到 4G**。四个容器实测吃 1.2～1.6G（Redis 那点计数几乎不占），大头是向量模型和 MySQL；2G 会很紧。
- **带宽用"按使用流量"**（大陆 ¥0.8/GB，只算出方向，不走流量不收费）。开了 gzip、压过图之后，
  一个访客大约 0.6MB，一千人次不到一块钱，比"按固定带宽"买小水管划算得多。
- **国内地域想用域名走 80/443，必须先 ICP 备案**（1～3 周）。不备案也能用，但只能
  `http://公网IP:端口` 这种形式，浏览器还会标"不安全"。

### 步骤

```bash
apt-get update && apt-get install -y docker.io docker-compose-v2 git
git clone https://github.com/nzbyb/lab-agent.git /opt/lab-agent && cd /opt/lab-agent
cp .env.example .env      # 然后填 JWT_SECRET_KEY（现生成）、LLM_* 三项
docker compose up -d --build
bash scripts/init-demo.sh --username 你的账号名 --admin   # 灌演示数据 + 建管理员
```

`.env` 里的密钥一律在服务器上现填，别把本机那份传上去。JWT 密钥用
`python3 -c "import secrets;print(secrets.token_urlsafe(48))"` 生成——后端启动时会自检，
太短或者用了模板里的示例值会直接拒绝启动。

### 代码改完之后怎么更新线上

```bash
cd /opt/lab-agent
git pull
docker compose up -d --build
docker compose ps
```

四条注意：

- **必须带 `--build`**。代码是打进镜像里的，compose 里没有挂载源码目录，只 `restart`
  等于跑的还是旧代码。构建期间网站照常能用（还是旧版容器），最后一刻换容器时会断几秒。
- **新增了基础镜像时，先在服务器上把它拉下来**。服务器连不通 Docker Hub，
  镜像又不在本地的话，`up` 会卡在拉取那一步报错退出——**而旧容器照常跑，看着像更新成功了**。
  先查再拉（以新增 Redis 那次为例）：

  ```bash
  docker images | grep -E 'redis' || true        # 没有输出 = 本地没有
  docker pull public.ecr.aws/docker/library/redis:7-alpine
  docker tag  public.ecr.aws/docker/library/redis:7-alpine redis:7-alpine
  docker images | grep redis                     # 能看到 redis:7-alpine 再往下走
  ```
- **别重跑 `scripts/init-demo.sh`**。它是首次部署时灌演示数据 + 建账号用的，重跑会把
  演示数据冲掉。更新只做上面这些。
- 前端会重新 `npm run build`，后端那两层装包的步骤只要 `requirements.txt` 没动就走缓存，
  通常几秒到一两分钟（国内网络下第一次构建那十几分钟只会有一次）。

更新完想确认拿到的是新版，可以查镜像里的文件，而不是靠刷浏览器：

```bash
docker compose exec -T backend grep -c "某个新函数名" /app/app/services/xxx.py
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/      # 期望 200
```

> 一个容易撞上的情况：如果 `git pull` 报
> `error: Your local changes to the following files would be overwritten by merge`，
> 说明**服务器上这几个文件被人手工改过**。别用 `git checkout --` 直接丢掉（可能丢掉有用的改动），
> 先看差异 —— `git --no-pager diff --ignore-cr-at-eol origin/main -- <文件>`；
> 忽略换行符后如果没有输出，就是只差换行符（服务器多半没设 `core.autocrlf`，
> 而 Windows 上通常设了 `true`，同一份文件两边字节不同），这时用
> `git stash push -m "..." -- <文件>` 把这几个文件先存起来再 pull，存起来的东西随时能拿回来。

### 国内网络下的三个坑

这三条是在国内服务器上部署时真实撞到的，换个网络环境就都不存在：

**1. Docker Hub 拉不动。** DNS 被污染（`registry-1.docker.io` 解析到 Facebook 的 IP），
直连必然超时；阿里云自带的镜像加速器对**没缓存过的**镜像也会返回 404。可用做法是绕开 Docker Hub，
从亚马逊官方的镜像站取——它是 Docker Hub 官方镜像的原样镜像：

```bash
docker pull public.ecr.aws/docker/library/python:3.11-slim
docker tag  public.ecr.aws/docker/library/python:3.11-slim python:3.11-slim   # 打回原名字
```

五个基础镜像（`python:3.11-slim`、`node:24-slim`、`mysql:8.4`、`nginx:alpine`、`redis:7-alpine`）都这么处理一遍，
`docker compose build` / `up` 就会直接用本地的，构建脚本一个字都不用改。

**2. pip 源不通、PyTorch 源慢到没法用。** 官方 PyPI 连不上，`download.pytorch.org` 实测只有
16 KB/s（torch 的 CPU 版有 200 多兆，这个速度得下几个小时）。所以 `backend/Dockerfile` 把 pip 源
做成了**可覆盖的构建参数**，默认值仍是官方源（本机、CI、国外部署行为不变），国内在 `.env` 里指过去：

```bash
PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
TORCH_INDEX_URL=https://mirror.sjtu.edu.cn/pytorch-wheels/cpu
```

> 注意 `mirrors.aliyun.com/pytorch-wheels/cpu` 是**文件列表，不是 pip 索引**，当 `--index-url`
> 用会解析失败——实测两个写法都不行，最后用的是上海交大那份镜像。

**3. 向量模型别用 scp 传。** HuggingFace 的缓存目录里全是符号链接（快照 → blobs → blobs/xx/…），
而 Windows 自带的 scp 不跟随符号链接，传过去只有半个缓存，运行时照样报缺文件。让服务器自己下更快：

```bash
docker compose run --rm -e HF_ENDPOINT=https://hf-mirror.com backend \
  python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5')"
```

（`-e HF_ENDPOINT=...` 指到国内镜像站，25 秒下完。缓存挂在 compose 里的 `.hf-cache` 卷上，只需下一次。）

### 上线后做的两处优化

都是实测出来的数字：

- **nginx 开 gzip**：官方镜像默认只压 `text/html`，JS/CSS 一律不压。主包 **837 KB → 261 KB**。
  但**千万别把 `text/event-stream` 列进 `gzip_types`**——AI 回答走 SSE 流式，而 gzip 要攒够一块
  才能压，列进去打字机效果就没了。
- **封面图压到宽 800px**：**445 KB → 86 KB**，并给 `/uploads` 加上 30 天缓存头。

两处加起来，首屏从约 2.2 MB 降到约 0.6 MB。

### 数据库备份

线上每天凌晨 3:20 自动导出一份 MySQL，保留最近 7 天，文件在服务器的 `/opt/lab-agent/backups/`，
文件名形如 `lab_agent-20261017-032015.sql.gz`。用 systemd timer 而不是 cron：精简的云镜像不一定装了
cron，systemd 一定有，还自带 `journalctl` 日志和「错过了就开机后补跑」。

装到服务器上（仓库在 `/opt/lab-agent`）：

```bash
cd /opt/lab-agent
sudo cp scripts/lab-agent-backup.service scripts/lab-agent-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lab-agent-backup.timer
sudo systemctl list-timers lab-agent-backup.timer      # 看下一次什么时候跑
```

先手动跑一次，确认真能出文件——**以 `ls` 看到的文件为准，不以脚本说「完成」为准**：

```bash
sudo /opt/lab-agent/scripts/backup-db.sh
ls -lh /opt/lab-agent/backups/
```

脚本里不含密码：`mysqldump` 跑在 mysql 容器**里面**，直接读容器自己的 `$MYSQL_ROOT_PASSWORD`，
所以这个文件可以公开，命令行历史和进程列表里也看不到口令。导出先写 `.part`，校验大小和 gzip 完整性
之后才改名，所以中途失败的半个文件不会冒充「最近一份备份」；`set -o pipefail` 保证 mysqldump 失败
不会被 gzip 的成功退出码盖住。

恢复（**先把目标库清空再导入**）：

```bash
gunzip < backups/lab_agent-20261017-032015.sql.gz | docker compose exec -T mysql sh -c \
  'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --default-character-set=utf8mb4 lab_agent'
```

**局限要说清楚**：备份和数据库在同一台机器上，能救「误删库、某张表写坏了」，救不了「整台服务器没了」。
建议每周从服务器下载一份到自己的电脑。

### 性能

机器就是线上那台：阿里云 ECS，**2 vCPU / 4 GiB**，后端单进程（没开 `--workers`，原因见前面 Docker 那节），
MySQL 和 Redis 在同一台。2026-10-17 用 `scripts/bench.py` 对着 `http://127.0.0.1:8080` 压的。
两个方向都要说明：压测程序和服务抢同一颗 CPU，真实能力比这组数字略好；但每个请求都**新开 TCP 连接**
（不复用），又比浏览器带 keep-alive 的场景更悲观。

| 接口 | 并发 | RPS | p50 | p95 | p99 | 错误率 |
| --- | --- | --- | --- | --- | --- | --- |
| `/api/lab/list?page=1&page_size=10` | 1 | 180.0 | 5ms | 6ms | 8ms | 0.00% |
| `/api/lab/list?page=1&page_size=10` | 10 | 193.2 | 50ms | 72ms | 89ms | 0.00% |
| `/api/lab/list?page=1&page_size=10` | 50 | 189.5 | 266ms | 423ms | 545ms | 0.00% |
| `/api/lab/1` | 1 | 250.3 | 4ms | 4ms | 5ms | 0.00% |
| `/api/lab/1` | 10 | 274.2 | 35ms | 48ms | 57ms | 0.00% |
| `/api/lab/1` | 50 | 281.4 | 174ms | 321ms | 413ms | 0.00% |
| `/api/equipment/list?page=1&page_size=10&lab_id=1` | 1 | 180.6 | 5ms | 6ms | 7ms | 0.00% |
| `/api/equipment/list?page=1&page_size=10&lab_id=1` | 10 | 190.3 | 52ms | 69ms | 78ms | 0.00% |
| `/api/equipment/list?page=1&page_size=10&lab_id=1` | 50 | 188.2 | 264ms | 453ms | 605ms | 0.00% |

九轮合计约 **1.9 万次请求，0 错误、0 个 429**。

怎么读这组数：

- **并发 1 时 p50 只有 4~5 ms**，单次查询本身很轻，慢不在这。
- **吞吐在 180~280 RPS 就顶住了**，并发从 1 加到 50 几乎不涨——这台机器的天花板就在这里。
  多出来的请求没有丢，全在排队：p50 从 5 ms 涨到 260 ms。也就是说它的失效方式是「变慢」，
  不是「报错」。
- 对一个面向全校的预约系统这是够用的：100 个人同时点、每人每秒一次，也就 100 RPS。
  要再往上，先得解决单进程（见「已知限制」里迁移和多 worker 那条），再谈加机器。

没有压 AI 接口：它的耗时在大模型那边，不在这台服务器；而且有 20 次/分钟的限流，
压出来只会是限流器的数字。

### AI 评测集

`backend/scripts/eval_questions.json` 里有 20 道题，分四类：开放时间（周中、周六、深夜三套时钟）、
预约规则、设备与安全规范、以及必须查库才能答对的事实（几间实验室、容量、位置、某台设备在哪）。
`backend/scripts/eval_agent.py` 逐题调用真实 Agent，按关键词判分，并把每道题的完整回答写进 JSON 报告。

```bash
cd backend
python scripts/eval_agent.py --list                  # 只看题目，不花钱
python scripts/eval_agent.py                         # 跑全部 20 题
python scripts/eval_agent.py --only open-saturday    # 调试单题
```

开放时间这几题必须钉死时钟：不钉的话「现在有哪些实验室开放」每天答案都不同，没法复现。脚本在跑之前
把 `agent_service.datetime`、`agent_tools.datetime`、`lab_service._now` 三处读时钟的地方换成一个返回
固定时刻的实现，每道题自带 `now`。脚本也只肯连本机数据库——题目绑定的是 `demo_data.sql` 的数据，
连到线上库这些数字全变，测了也没意义。

**2026-10-17 实测：20/20 通过**（模型 `deepseek-flash`，本机开发库，8 间实验室的那套数据）。

判分靠关键词，局限是「答对了但换了说法」也会判错，所以失败项要人眼看原文；反过来，题目本身也可能偏容易。
它真正守的是**回归**：改完提示词或工具之后，这 20 道题的结论不能变。

---

## 测试

```bash
cd backend
.venv\Scripts\python -m pytest
```

跑之前要**另建一个空库**，`conftest.py` 只会建表、不会建库：

```sql
CREATE DATABASE lab_agent_test DEFAULT CHARSET utf8mb4;
```

`conftest.py` 会把 `.env` 里的库名强行改成 `lab_agent_test`，所以不用你去配。它有两道保险丝，防的是「测试把开发库清了」这件事：一道查改完之后的库名，另一道**直接查 `engine` 真正连上的库**——上一次出事故就是因为某个 pytest 插件在 `conftest` 之前就 import 了 `app`，导致环境变量覆盖没生效，改动被静默吞掉。所以第二道才是真正兜住的那道。

前端跑 vitest（不需要起后端、不需要数据库）：

```bash
cd frontend
npm test          # vitest run，跑完就退出
npm run test:watch   # 开发时盯着改
```

覆盖 `src/utils/auth.js`、`src/utils/request.js`、`src/stores/user.js` 三个模块——都是纯逻辑，用 `happy-dom` 提供的 `localStorage` 就够，不渲染任何组件、不加载 Element Plus，所以跑一遍不到 1 秒。重点守的是三处真实踩过的坑：登出必须同时清掉内存里的用户信息（只清 localStorage 的话侧边栏要刷新才消失）、401 只弹一条提示、`saveLoginData` 不能漏掉 `setToken`。

另外还有构建验证：`cd frontend && npx vite build`。

CI（GitHub Actions）跑的就是上面这些，前后端各一个 job。后端那个用真的 MySQL 服务容器而不是 SQLite——这套代码用到行锁（`test_concurrency` 那组用例），SQLite 没有，测出来的绿是假的；跑完会把 pytest 的最后一行汇总写进 job 摘要（`$GITHUB_STEP_SUMMARY`）。前端那个跑 `npm ci` + `npm test` + `npm run build`。

> 前端测试用**变异检验**证明过有效：把上面那三处逻辑逐一改坏（logout 不清内存、前缀判据换成 `includes`、`isAdmin` 写成「非 student 即管理员」、漏掉 `setToken`、401 只清 localStorage、401 弹两条 toast），六个变体全部被对应用例抓红。跑通不算数，**改坏了会红**才算数。

## 目录结构

```
backend/
  app/
    api/           路由层，多数接口只做参数校验和转发（文件上传、AI
                   流式对话这两个是在层内自己处理的）
    services/      业务逻辑都在这里
    models/        SQLAlchemy 模型
    schemas/       Pydantic 出入参
    common/        统一响应体和异常处理
    dependencies/  登录态、管理员校验
  migrations/      Alembic 迁移，表结构的每一次变更都落在这里
  tests/           228 条用例
  demo_data.sql    实验室 / 设备基础数据
  scripts/         演示预约数据生成、AI 评测集（eval_agent.py + eval_questions.json）
  Dockerfile
frontend/
  src/
    views/         15 个页面
    api/           按后端模块分的请求封装
    components/    BaseChart 等复用组件
    stores/        Pinia
    utils/         请求封装、登录态读写（旁边的 __tests__/ 是 vitest 用例）
  vitest.config.js 前端测试配置
  Dockerfile       node 构建 → nginx 托管
  nginx.conf       静态文件 + 反代 /api、/uploads
scripts/
  init-demo.sh     一键初始化：灌数据 + 注册账号 + 造演示预约
  backup-db.sh     导出 MySQL 到 backups/（配合同目录的 systemd timer，每天 3:20）
  bench.py         只读接口压测，只依赖标准库
docs/              图标和界面截图
docker-compose.yml MySQL + 后端 + 前端
```

---

## 几处实现细节

**并发预约用 MySQL 命名锁。** 两个人同一秒抢同一个时段，光靠「先查有没有冲突、再写入」会双双通过。这里用 `GET_LOCK` 把「检查冲突 + 写入」锁成一个原子段。锁名按「实验室 + 日期」取（`lab_agent:book:<lab_id>:<date>`），不是每台设备各一把——因为约整间实验室和约其中某台设备会互相占用（见知识库《设备使用说明》），两者必须共用一把锁，否则两个请求各拿各的锁、各查各的，都说没冲突、然后双双写进去。不同实验室之间仍然互不影响；代价是同一间实验室里两台不同设备的预约也会排一下队，而临界区只有「查一次 + 插一条」，毫秒级。

**AI 一轮里并发调多个工具时，每个工具各开一个数据库会话。** LangGraph 的 `ToolNode` 用 `asyncio.gather` 并发跑同一轮的工具调用，同步工具会被丢进各自的线程。它们要是共用一个 SQLAlchemy `Session`，SQLAlchemy 会直接拒绝：`This session is provisioning a new connection; concurrent operations are not permitted`。更麻烦的是会话被弄坏之后，这一轮剩下的查询会全部跟着失败，用户看到的就是「这个功能坏了」。改成每个工具自己 `with SessionLocal() as db` 之后，实测 8 个并发查询从 7 个失败变成全部成功。`tests/test_concurrency.py` 里有这条回归用例。

**AI 的回答是流式的，而且中途断线不丢内容。** 后端用 SSE 边生成边推，前端手写 `fetch` + `ReadableStream` 解析（全站只有这一处没走 axios）。用户关掉网页的那一刻，生成器会被取消——抛的是 `CancelledError`，它不属于 `Exception`，兜底的 `except Exception` 拦不住。所以「把这一轮存进数据库」放在 `finally` 里，用户的提问则在开始吐字之前就落库。关掉标签页再打开，这一轮对话还在。

**同时在跑的 AI 对话有上限（默认 3 个）。** 每次对话占一条流式连接，还要在本机跑一次向量检索，2C4G 的机器上开太多会互相拖慢。超过上限的新请求直接回一句"现在同时使用 AI 的人有点多，请过一会儿再试"，不排队——排队只会把连接和内存继续占着。这个数由环境变量 `AI_MAX_CONCURRENCY` 调。名额在清理逻辑里一定还：用户中途关网页时生成器被取消，走的是 `finally` 而不是普通代码。

**给 AI 查的知识库是本地向量检索。** `backend/data/kb/` 下 4 份 Markdown（开放时间、预约规则、设备使用、安全规范）用 ChromaDB 建索引，embedding 模型在本地跑，不用调外部接口——但**第一次要能从 HuggingFace 把模型下下来**。向量库本身不进仓库（`backend/data/chroma/` 被忽略），所以新克隆的仓库没有现成索引。

**embedding 模型只认本地缓存，装载时不再联网。** 加载时传的是 `local_files_only=True`。这个联网检查在国内网络下代价极大：`huggingface_hub` 每次装载都要 `HEAD` 一次 huggingface.co 取 commit hash，而国内连 TCP 都建不起来，要卡满 21 秒（`WinError 10060`）才放弃，而且还要重试 5 次。实测同一个模型：联网检查要 **308 秒**，不联网只要 **5.6 秒**。这笔时间全落在启动上，而 uvicorn 的监听端口是等 lifespan 跑完才建的——启动期间前端发什么都连不上。所以「热重载太慢」和「老是连接失败」是同一个病，不是两件事。

本地缓存里没有这个模型时（新克隆的仓库第一次启动就是这样），会自动退回联网那条路去下载，只慢这一次。

想换模型版本，把缓存目录改名或删掉即可，下次启动会重新下载：`~/.cache/huggingface/hub/models--BAAI--bge-small-zh-v1.5`（Windows 上是 `C:\Users\<用户名>\.cache\huggingface\hub\` 下的同名目录）。**但换完必须手工删掉 `backend/data/chroma/`**：索引指纹只看 `data/kb/` 里 md 的文件名和内容，认不出模型换了，不删就会继续拿旧向量用——新旧向量不在同一个空间里，检索不会报错，只会悄悄变差。

**其中「开放时间.md」是生成的，不要手改。** 后端启动时、以及管理员在管理端增删改实验室之后，都会按 `labs` 表把它重画一遍（文件头也写了这句），手改会在下一次被覆盖。想调开放时间请走管理端的「实验室管理」——那边改完，知识库、AI 工具、界面三处是同一个来源，不会各说各话。

**改了 md 不用再手工删向量库。** 索引靠一份内容指纹判断新旧：文件内容变了，下一次 AI 检索时就地 `upsert` 增量重建（不是先删后建，中途失败老索引还在，指纹也只在重建成功后才写，失败了下次会重试）。整个重建过程不占管理端请求线程，也不占启动流程。

**错误响应分两套，不是全 200。** 业务异常走 HTTP 200，状态放在 body 的 `code` 里；但鉴权失败是真的 HTTP 401，参数校验失败 422，触发限流 429。前端拦截器两条路各判一次 401（一条看 body 里的 `code`，一条看 HTTP 状态码），都会登出、跳登录页，并把后端那句原因提示出来。

body 里的 `code` 有一套约定，照着它就能分清"这次请求哪里不对"：**400** 业务规则不允许（默认，比如密码错、时段被占）、**403** 登录了但没这个权限、**401** 没登录或令牌失效、**422** 参数格式不对、**429** 限流，而 **500 只留给真正的服务端故障**（由全局兜底抛出，业务代码不该主动用）。这条约定是补上的：在此之前 56 处业务错误全都回 500，于是"密码输错了"在接口层面报的是"服务器错误"。

**429 会告诉你还要等几秒。** 响应头带 `Retry-After`（秒），body 里那句提示也写着秒数。没有它的话，用户只知道"太频繁了"，不知道等三秒还是一分钟，最容易的做法就是马上再点一次，然后继续吃 429。

**登录按「IP + 账号」计数，别人试错密码不会把你锁住。** 同一个账号在同一个 IP 上 5 次/分钟，超了就要等一分钟。额度只跟着"这个 IP 上的这个账号"走——校园网、公司网几十个人共用一个出口 IP 时，同事连错几次密码，不会连累你登录。另外还有一条按 IP 的 60 次/分钟兜底，专门挡"同一个 IP 换着账号撞库"，给得宽就是因为共用出口 IP 的场景。

**改密码会把这个人所有设备踢下线。** 每张令牌里带着签发那一刻的令牌版本号（`users.token_version`），改密码时版本号 +1，旧令牌下一个请求就在 `dependencies/auth.py` 里对不上号被拒。这个比对不额外查库——鉴权本来每个请求就要查一次用户。注意"立刻失效"的准确含义是**下一个请求即失效**，没有推送通道，纯打开的标签页要等它下次发请求才会被踢。管理员重置他人密码（`PUT /api/user/{id}/password`）走的是同一套：重置同样 +1，否则"号被盗了"这个场景下重置等于没做。

**密码的长度边界是 3 ~ 72 字节，注意是字节。** 上限不是我们的规定，是 bcrypt 的规定：bcrypt 5.0 碰到超过 72 字节的输入**直接抛异常**，不是老版本那种静默截断，不拦就是 HTTP 500。而一个汉字在 UTF-8 里占 3 字节，所以 24 个汉字就到顶了——按字符数卡会漏掉所有中文密码。下限只在"设置新密码"时管（注册、新建用户、改密码、重置密码四处共用一份规则），**登录那条路刻意不卡下限**：库里存着当年没卡过长度时注册的短密码，卡了等于把人锁在门外，而且报的错还跟密码对不对毫无关系。

## 已知限制

- **限流计数在 Redis（Docker 部署默认如此）**，多进程/多实例共用一份，**后端**重启不清零。注意 Redis 容器或整机重启会清零——计数刻意不落盘（没有挂卷、关了 RDB/AOF），因为丢了最坏只是重置一分钟的额度。代价是多了一个要维护的容器；Redis 挂了会退回各进程自己的内存计数——网站照常可用，但那段多实例部署时会变成"每台各算一份"。
- **下线是"一锅端"，踢不了单独某一台设备。** 改密码让该用户**全部**旧令牌失效，做不到"只踢被盗的那一台、保留其他设备"。要精确到单枚令牌得引入会话表，那是另一件事。
- **登出只清浏览器，不通知后端。** 没有 logout 接口，退出登录就是删掉本地令牌，那枚令牌在过期前（默认 24 小时）仍然有效。想让它立刻作废只能改密码。
- **迁移在服务启动时执行，假设单进程。** uvicorn 开多 worker 时每个进程都会跑一遍，并发 DDL 会撞车；要让多 worker 同时启动，得把 `run_migrations()` 从 lifespan 挪到部署流程里单独执行，或者用 MySQL 的 `GET_LOCK` 包一层（`reservation_service` 里已有现成用法）。
- **单进程的吞吐上限约 200 RPS**（实测 180~280，见上面「性能」）。这不是调参能补的，要先解决上一条。
- **关掉标签页后，这一轮回答会停在那里。** 内容不会丢（`finally` 里落了库），但后端不会接着写完，重新打开看到的是半截。已计划改成后台任务继续生成。
- **对话历史每人最多留 50 个会话**（按会话裁，不是按消息条数），超了删最旧的。
- 没有 pre-commit 钩子。（CI 和 Docker 都补上了：前者是 GitHub Actions 跑前后端各一个 job，后者见上面「跑起来」。）

## 界面

![AI 助手](docs/screenshots/ai-chat.png)

![实验室列表](docs/screenshots/lab-list.png)

![我的预约](docs/screenshots/my-reservation.png)

![管理员审核](docs/screenshots/audit.png)

## 开源许可

MIT，全文见根目录的 [`LICENSE`](LICENSE)。
