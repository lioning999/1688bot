"""Telegram bot 配置 — 与后端共享 src/api/.env（密钥唯一来源，禁止硬编码）。"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # 项目根目录
load_dotenv(BASE_DIR / "src" / "api" / ".env")


class Config:
    # ---- 必需 ----
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    BOT_SECRET: str = os.getenv("BOT_SECRET", "")  # bot→后端 鉴权共享密钥
    BOT_API_BASE: str = os.getenv("BOT_API_BASE", "http://127.0.0.1:8008").rstrip("/")

    # ---- 轮询 / 超时 ----
    POLL_TIMEOUT: int = int(os.getenv("BOT_POLL_TIMEOUT", "30"))      # getUpdates 长轮询秒数（Telegram 上限 50）
    ANALYZE_POLL_INTERVAL: int = int(os.getenv("BOT_ANALYZE_INTERVAL", "3"))  # 轮询分析状态间隔
    ANALYZE_MAX_WAIT: int = int(os.getenv("BOT_ANALYZE_MAX_WAIT", "90"))      # 分析最长等待秒数

    @classmethod
    def validate(cls) -> None:
        missing = [name for name, val in (
            ("TELEGRAM_BOT_TOKEN", cls.TELEGRAM_BOT_TOKEN),
            ("BOT_SECRET", cls.BOT_SECRET),
        ) if not val]
        if missing:
            raise ValueError(f"❌ bot 必填配置缺失: {', '.join(missing)}。请检查 src/api/.env")
