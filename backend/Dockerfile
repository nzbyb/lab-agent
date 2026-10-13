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

# 单进程，刻意不加 --workers。
# 这个应用有好几处进程内状态：知识库重建用的 threading.Lock、
# 限流器、embedding 模型对象。开多 worker 会各自持有一份，
# 锁形同虚设、限流变成 N 倍。要扩得先把这些挪到进程外，现在别动。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
