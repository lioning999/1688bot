"""JWT 工具 — 签发 + 验证。密钥和有效期从 Config 读取。"""

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from config import Config


def create_token(user_id: int, email: str | None = None, default_lang: str | None = None) -> str:
    """签发 JWT access token（HS256，90 天过期）。

    Args:
        user_id: 用户 ID
        email: 用户邮箱，可选
        default_lang: 用户默认语言，可选

    Returns:
        encoded JWT 字符串
    """
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "user_id": user_id,
        "email": email or "",
        "default_lang": default_lang or "",
        "iat": now,
        "exp": now + timedelta(minutes=Config.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, Config.JWT_SECRET_KEY, algorithm=Config.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """解码 JWT token。

    Args:
        token: Bearer token 字符串（去掉 'Bearer ' 前缀）

    Returns:
        解码后的 payload

    Raises:
        jwt.ExpiredSignatureError: token 已过期
        jwt.InvalidTokenError: token 无效或被篡改
    """
    return jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=[Config.JWT_ALGORITHM])
