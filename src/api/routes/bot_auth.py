"""Telegram bot 鉴权 — bot 进程用 BOT_SECRET + telegram_uid 换取 JWT。

流程：bot 收到用户消息 → 调 POST /api/bot/login（带 BOT_SECRET + telegram_uid）
  → 后端取/建用户 → 签发 JWT → bot 后续请求带 Bearer token（复用现有 token 校验）。
EXEMPT：bot 进程没有用户 JWT，此端点未登录可用（middleware EXEMPT_PREFIXES 白名单）。
"""

import hmac
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, field_validator

from config import Config
from services.auth_svc import auth_service
from utils.exceptions import AppError
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


class BotLoginRequest(BaseModel):
    """bot/login 请求体。telegram_uid 必须是纯数字（Telegram user_id 为数字）。"""

    telegram_uid: str
    secret: str

    @field_validator("telegram_uid")
    @classmethod
    def must_be_digits(cls, v: str) -> str:
        if not v or not v.isdigit():
            raise ValueError("telegram_uid 必须是数字")
        return v.strip()


@router.post("/api/bot/login")
async def bot_login(body: BotLoginRequest) -> dict[str, Any]:
    """bot 登录：校验 BOT_SECRET → 取/建用户 → 签发 JWT。"""
    # 1. BOT_SECRET 恒定时间比较（防时序攻击；未配置则拒绝）
    if not Config.BOT_SECRET or not hmac.compare_digest(body.secret, Config.BOT_SECRET):
        raise AppError(message="bot 鉴权失败", code="BOT_AUTH_FAILED",
                       msg_code="BOT_AUTH_FAILED", http_status=401)

    # 2. 取/建用户 + 签发 JWT（secret 已校验，不 log 不落响应体）
    result = await auth_service.bot_login(body.telegram_uid)

    return {"code": 200, "msg_code": "OK", "data": result, "message": "ok"}
