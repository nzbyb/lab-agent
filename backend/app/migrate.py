"""部署时单独执行的数据库迁移入口。

用法（在 backend 目录、装好依赖并配好 .env 之后）：

    python -m app.migrate

docker-compose 里有一个同名的 `migrate` 服务会自动跑这一步；后端容器
不再在启动时建表，所以多 worker/多副本同时起来也不会并发跑 DDL。
"""

from app.database import run_migrations


def main() -> None:
    run_migrations()
    print("数据库已升到最新版本")


if __name__ == "__main__":
    main()
