"""配置中心 — 从 .env 读取配置，启动时验证必填项。"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from dotenv import load_dotenv

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 加载 .env（只在 config.py 中调用一次）
load_dotenv(BASE_DIR / "src" / "api" / ".env")

# 多 token 轮换：免费账号每日配额有限，配额耗尽自动切换下一个
# 读取 APIFY_TOKEN1 ~ APIFY_TOKEN9，遇到空值停止
_APIFY_TOKENS: list[str] = []
for _i in range(1, 10):
    _t = os.getenv(f"APIFY_TOKEN{_i}", "")
    if _t:
        _APIFY_TOKENS.append(_t)


@dataclass
class Config:
    """全局配置。所有业务常量集中在此，代码中引用 Config.XXX。"""

    # ---- 应用 ----
    APP_NAME: str = os.getenv("APP_NAME", "Sourcely")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    TEST_MODE: bool = os.getenv("TEST_MODE", "false").lower() == "true"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me")
    PORT: int = int(os.getenv("PORT", "8008"))

    # ---- 数据库 ----
    DB_HOST: str = os.getenv("DATABASE_HOST", "localhost")
    DB_PORT: int = int(os.getenv("DATABASE_PORT", "3306"))
    DB_USER: str = os.getenv("DATABASE_USER", "root")
    DB_PASSWORD: str = os.getenv("DATABASE_PASSWORD", "")
    DB_NAME: str = os.getenv("DATABASE_NAME", "sourcely_DB")
    DB_POOL_MIN: int = int(os.getenv("DB_POOL_MIN", "5"))
    DB_POOL_MAX: int = int(os.getenv("DB_POOL_MAX", "20"))

    # ---- JWT ----
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "change-me")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

    # ---- Google OAuth 2.0 ----
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "")
    GOOGLE_AUTH_URL: str = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_URL: str = "https://oauth2.googleapis.com/token"
    GOOGLE_CLOCK_SKEW: int = 60

    # ---- Apify 1688 数据采集 ----
    # 多 token 轮换：免费账号每日配额有限，配额耗尽自动切换下一个 token
    APIFY_TOKENS: ClassVar[list[str]] = _APIFY_TOKENS
    APIFY_TOKEN: str = _APIFY_TOKENS[0] if _APIFY_TOKENS else ""  # 向后兼容
    APIFY_ACTOR_ID: str = os.getenv("APIFY_ACTOR_ID", "zen-studio~1688-wholesale-scraper")
    APIFY_WAIT_SECONDS: int = int(os.getenv("APIFY_WAIT_SECONDS", "90"))
    APIFY_DAILY_FREE_LIMIT: int = int(os.getenv("DAILY_FREE_LIMIT", "3"))
    APIFY_DAILY_LOGIN_LIMIT: int = int(os.getenv("DAILY_LOGIN_LIMIT", "10"))
    URL_1688_DETAIL: str = "https://detail.1688.com/offer/{offer_id}.html"

    # ---- 业务常量 ----
    CNY_USD_RATE: float = float(os.getenv("CNY_USD_RATE", "7.2"))
    TASK_TTL: int = int(os.getenv("TASK_TTL", "1800"))

    # ---- 汇率（1 USD = X 本地货币） ----
    FX_VND: float = float(os.getenv("FX_VND", "25450"))
    FX_THB: float = float(os.getenv("FX_THB", "35.7"))
    FX_IDR: float = float(os.getenv("FX_IDR", "16100"))
    FX_MYR: float = float(os.getenv("FX_MYR", "4.65"))
    FX_PHP: float = float(os.getenv("FX_PHP", "57.2"))

    # ---- Qwen3 翻译（新加坡节点，OpenAI 兼容接口） ----
    QWEN_API_KEY: str = os.getenv("QWEN_API_KEY", "")
    QWEN_MODEL: str = os.getenv("QWEN_MODEL", "qwen-flash")
    QWEN_API_BASE: str = os.getenv("QWEN_API_BASE", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")

    # ---- 日志 ----
    LOG_DIR: str = os.getenv("LOG_DIR", "")

    # ---- Sentry 错误监控 ----
    SENTRY_DSN: str = os.getenv("SENTRY_DSN", "")

    @classmethod
    def validate(cls):
        """启动时校验必填配置。缺失报错，防止带病启动。"""
        required = [
            ("SECRET_KEY", cls.SECRET_KEY),
            ("JWT_SECRET_KEY", cls.JWT_SECRET_KEY),
            ("DATABASE_HOST", cls.DB_HOST),
            ("DATABASE_NAME", cls.DB_NAME),
            ("GOOGLE_CLIENT_ID", cls.GOOGLE_CLIENT_ID),
            ("GOOGLE_REDIRECT_URI", cls.GOOGLE_REDIRECT_URI),
        ]
        missing = [name for name, val in required if not val or val == "change-me"]
        if missing:
            raise ValueError(f"❌ 必填配置缺失: {', '.join(missing)}。请检查 .env 文件。")
