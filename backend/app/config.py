from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # 后端项目的根路径


class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET_KEY: str
    JWT_EXPIRE_HOURS: int = 24
    JWT_ALGORITHM: str = "HS256"
    LLM_API_KEY: str
    LLM_MODEL: str
    LLM_BASE_URL: str

    # 跨域白名单，逗号分隔。只有前后端分开跑（本机 npm run dev，前端在 5173）时才用得上；
    # 上线让前后端同域（nginx 把 /api 反代给后端）就不发预检请求了，留空也不影响。
    # 这里刻意用 str 而不是 list[str]：pydantic-settings 见到列表字段会把值当 JSON 解析，
    # 写成 a,b 会直接报错，只有 ["a","b"] 才认——让它自己 split 更好用。
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8"
    )


settings = Settings()

# 出现这些值说明直接照抄了 .env.example，必须拒绝启动
_WEAK_JWT_SECRETS = {
    "please_generate_a_random_secret_at_least_32_chars",
    "your_secret_key",
    "secret",
    "changeme",
}


def _validate_jwt_secret() -> None:
    """启动自检：拒绝弱密钥，避免带着示例配置上线"""
    secret = settings.JWT_SECRET_KEY.strip()
    if len(secret) < 32 or secret in _WEAK_JWT_SECRETS:
        raise RuntimeError(
            "JWT_SECRET_KEY 不合法：长度至少 32 位，且不能使用 .env.example 里的示例值。\n"
            '生成方法：python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )


_validate_jwt_secret()

UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 白名单转成列表，顺手丢掉空项——写成 "a, b," 这种带尾逗号的形式也不会多出一个空字符串
ALLOWED_ORIGINS = [
    origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()
]
MAX_FILE_SIZE = 100 * 1024 * 1024

ALLOWED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".zip",
}
