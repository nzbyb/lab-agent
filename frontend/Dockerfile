# ============================================================
# 前端镜像：两阶段构建
#   第一阶段用 node 把源码编成静态文件
#   第二阶段只把编出来的 dist 交给 nginx
# 最后镜像里没有 node、没有源码、没有 node_modules，只有一份静态文件 + nginx。
# ============================================================

# ---------------- 第一阶段：构建 ----------------
# 用 slim（Debian）而不是 alpine。alpine 是 musl libc，vite/rollup/esbuild
# 的原生二进制要挑 musl 版本，npm 处理 optionalDependencies 偶尔会挑错，
# 于是本机编得好好的、容器里报 "Cannot find module @rollup/rollup-linux-x64-musl"。
# 这层镜像最后会被丢掉，大一点无所谓，稳更重要。
FROM node:24-slim AS build

WORKDIR /app

# 先只拷依赖清单再 npm ci。
# 这样只要 package.json / package-lock.json 没动，这层就能命中缓存，
# 改源码重新构建时不用每次重装几百个包。
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# 生产构建。这里刻意**不传** VITE_API_BASE_URL：
#   src/utils/request.js 里写的是 `import.meta.env.VITE_API_BASE_URL || ''`，
#   空串就是相对路径，浏览器会把 /api/... 打到当前这个 nginx 上，
#   再由上面的 nginx.conf 转给后端容器。前后端同源，不产生跨域请求。
# 注意 src/api/ai.js 的流式接口走的是 fetch 不是 axios，但它也做了同样的
# `|| ''` 兜底 —— 之前漏了这层兜底，生产构建里会拼出 "undefined/api/ai/chat/stream"，
#   整个 AI 对话直接失效。那是本机 dev 环境（.env.development 有值）永远复现不出来的坑，
#   而 Docker 这套就是生产构建，正好是它的试金石。
RUN npm run build

# ---------------- 第二阶段：发静态文件 ----------------
FROM nginx:alpine

# nginx 官方镜像自带的默认站点配置会覆盖掉我们的，
# 直接把它那份替换掉，而不是新增一个 server 块 —— 两份都在的话
# 先加载的那个（默认配置）会抢走 80 端口，我们的反代会静默失效。
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
