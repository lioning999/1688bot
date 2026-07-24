"""Google OAuth 2.0 适配器 — 生成授权 URL + code 换 token + id_token 验证。"""

from typing import Any
from urllib.parse import quote

import httpx
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token  # type: ignore[import-untyped]

from config import Config
from utils.exceptions import ExternalServiceError
from utils.logger import get_logger

logger = get_logger(__name__)


class GoogleAuthAdapter:
    """Google OAuth 2.0 服务端流程适配器。

    流程：
    1. get_auth_url() → 前端跳转 Google 授权页
    2. exchange_code(code) → Google 回调后用 code 换 id_token
    """

    def get_auth_url(self, state: str = "") -> str:
        """生成 Google OAuth 授权页 URL。

        scope=openid+email+profile 为非敏感 scope，无需 Google 审核。
        state 参数由 Google 原样传回 callback，用于防 CSRF + 携带回调路径。
        """
        params = (
            f"client_id={Config.GOOGLE_CLIENT_ID}"
            f"&redirect_uri={Config.GOOGLE_REDIRECT_URI}"
            f"&response_type=code"
            f"&scope=openid+email+profile"
        )
        if state:
            params += f"&state={quote(state, safe='')}"
        return f"{Config.GOOGLE_AUTH_URL}?{params}"

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """用授权码换取 Google id_token。

        Args:
            code: Google 回调携带的一次性授权码

        Returns:
            id_token 解码后的 payload: {sub, email, name, picture}

        Raises:
            ExternalServiceError: Google token 端点调用失败或验证不通过
        """
        # 1. 用 code 换取 token
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.post(
                    Config.GOOGLE_TOKEN_URL,
                    data={
                        "code": code,
                        "client_id": Config.GOOGLE_CLIENT_ID,
                        "client_secret": Config.GOOGLE_CLIENT_SECRET,
                        "redirect_uri": Config.GOOGLE_REDIRECT_URI,
                        "grant_type": "authorization_code",
                    },
                )
                resp.raise_for_status()
                token_data = resp.json()
            except httpx.HTTPError as e:
                logger.error(f"Google token exchange failed: {e}")
                raise ExternalServiceError(service_name="Google", details={"phase": "token_exchange"}) from e

        # 2. 验证 id_token
        jwt_token = token_data.get("id_token")
        if not jwt_token:
            raise ExternalServiceError(service_name="Google", details={"phase": "verify", "reason": "no id_token in response"})

        try:
            payload = id_token.verify_oauth2_token(  # type: ignore[reportUnknownMemberType]
                jwt_token,
                google_requests.Request(),
                Config.GOOGLE_CLIENT_ID,
                clock_skew_in_seconds=Config.GOOGLE_CLOCK_SKEW,
            )
        except ValueError as e:
            logger.error(f"Google id_token verification failed: {e}")
            raise ExternalServiceError(service_name="Google", details={"phase": "verify", "reason": str(e)}) from e

        logger.info(f"Google auth success: sub={payload.get('sub', '')[:8]}... email={payload.get('email', '?')}")
        return dict(payload)


# 模块级单例
google_auth_adapter = GoogleAuthAdapter()
