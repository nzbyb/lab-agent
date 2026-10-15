# ============================================================
# 后端镜像：Python 3.11 + uvicorn
#
# 不带任何密钥。LLM_API_KEY、JWT_SECRET_KEY、DATABASE_URL 全部
# 由 docker-compose 在启动时从根目录 .env 注入环境变量，
# 所以这个镜像可以放心推到任何公开仓库。
# ============================================================
FROM python:3.11-slim

# PYTHONIOENCODING / LANG：容器默认 locale 是 C（ASCII）。这套代码里
#   到处是中文字符串（报错信息、日志、知识库文档），不设这个，
#   打印中文会直接抛 UnicodeEncodeError。
# PYTHONUNBUFFERED：不设的话 print 会攒在缓冲区里，docker logs 看不到实时输出，
#   线上排查时会以为"程序卡住了"。
ENV PYTHONIOENCODING=utf-8 \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ------------------------------------------------------------
# 时区。这行不是可有可无的。
#
# 整套代码用 datetime.now() 取"现在"，取的是容器本地时间，而容器默认是 UTC。
# 容器跑 UTC、人在东八区的话会差 8 小时：北京时间晚上 21:00 去问 AI
# "现在有哪些实验室开放"，容器以为才 13:00，会答"都开着"，而实际上早关门了
# ——这正是当初用户报的那个 bug 的形态，只不过这次是自己造的。
#
# 想换时区：docker compose build --build-arg TZ=Asia/Tokyo，
# 或在 compose 里给这个服务加 TZ 环境变量覆盖。
# ------------------------------------------------------------
ARG TZ=Asia/Shanghai
ENV TZ=${TZ}
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && ln -snf /usr/share/zoneinfo/${TZ} /etc/localtime \
    && echo ${TZ} > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ------------------------------------------------------------
# 先单装 CPU 版 torch，再装 requirements —— 顺序不能反。
#
# requirements.txt 里没有 torch，它是 sentence-transformers 的依赖，
# 会被自动带上。不先钉住 CPU 版的话，pip 默认去 PyPI 拉 CUDA 版，
# 镜像白白多个两三 G，而这个容器根本没有 GPU 可用。
# （CI 里是同一个道理，同一个写法。）
# ------------------------------------------------------------
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000

# ------------------------------------------------------------
# --forwarded-allow-ips 这行不能省。省了限流会变成"全站一个桶"。
#
# 前头站着 nginx，请求进到容器里时来源地址是**nginx 容器的地址**，不是访客的。
# 这个参数是告诉 uvicorn"哪些来源是可信的"，可信来源带来的
# X-Forwarded-For 才会被采信。不写的话默认只信 127.0.0.1，而 Docker 里
# 从 nginx 过来的是 172.x，于是访客 IP 全被忽略、所有请求算成同一个人：
# 登录注册的 5 次/分钟变成**全站共享**，任何一个访客刷 5 次，所有人（含他自己）
# 接下来 60 秒都登不上；AI 的 20 次/分钟同理。
#
# 172.16.0.0/12 覆盖 Docker 默认的网桥网段（172.17–172.31），
# 也就是 compose 自己建的那个网络。**不要图省事写 `*`**：那等于谁来都信，
# 一旦后端端口哪天暴露到公网，任何人都能伪造 IP 绕过限流。
#
# 注意：Docker Desktop（Windows/macOS）与 Linux 上的来源地址不一样，
# 换环境部署后要照 backend 的访问日志核一遍"看到的到底是谁的 IP"。
#
# 这一条要和 nginx 那边配套：**nginx 必须用 $remote_addr 覆盖**
# X-Forwarded-For，不能追加。追加的话，头里会是"访客伪造的, nginx 看到的"，
# 而 uvicorn 取的是"从右往左第一个不属于可信来源的地址"——万一 nginx 看到的
# 那个地址本身就在可信网段里（Docker Desktop 上宿主机来的请求就是，
# 进容器已经变成网桥网关 172.18.0.1），这一步会被跳过、取到伪造值，
# 限流就能被绕过。实测过：伪造 7 个不同 IP，7 次全放行。
# ------------------------------------------------------------

# 单进程，刻意不加 --workers。
# 这个应用有好几处进程内状态：知识库重建用的 threading.Lock、
# 限流器、embedding 模型对象。开多 worker 会各自持有一份，
# 锁形同虚设、限流变成 N 倍。要扩得先把这些挪到进程外，现在别动。
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--forwarded-allow-ips", "127.0.0.1,172.16.0.0/12"]
