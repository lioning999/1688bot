"""认证服务 — Google OAuth 登录/注册业务编排。"""

from typing import Any

from adapters.google_auth import GoogleAuthAdapter
from repositories.user_repo import UserRepository
from utils.jwt import create_token
from utils.logger import get_logger

logger = get_logger(__name__)

# 模块级单例 — routes 层不再直接 import adapter
_google_auth = GoogleAuthAdapter()
_user_repo = UserRepository()


class AuthService:
    """认证业务编排。"""

    def __init__(self, google_auth: GoogleAuthAdapter | None = None,
                 user_repo: UserRepository | None = None):
        self.google_auth = google_auth or _google_auth
        self.user_repo = user_repo or _user_repo

    def get_auth_url(self, state: str = "") -> str:
        """获取 Google OAuth 授权 URL（委托 adapter）。"""
        return self.google_auth.get_auth_url(state=state)

    async def login_with_google(self, code: str, default_lang: str | None = None) -> dict[str, Any]:
        """Google OAuth 登录/注册（自动判断）。

        流程：
        1. code 换 id_token → 验证 → 拿到 Google 用户信息
        2. 查 users 表：无记录 → 注册（INSERT）；有记录 → 更新 last_login
        3. 如果传了 lang 且与 DB 不同 → 更新 DB（PUT 失败的保底纠正）
        4. 签发自签 JWT（HS256，90 天）
        5. 返回 access_token + user

        Args:
            code: Google 回调的一次性授权码
            default_lang: 插件当前语言，首次登录写入，后续登录与 DB 比对更新

        Returns:
            {"access_token": "...", "user": {...}}

        Raises:
            ExternalServiceError: Google 端异常
        """
        # 1. 用 code 换已验证的 Google 用户信息
        payload = await self.google_auth.exchange_code(code)

        google_id = payload["sub"]  # sub 是 JWT 标准 claim，exchange_code 已验证 id_token，不可能为空
        email = payload.get("email")
        name = payload.get("name")
        avatar_url = payload.get("picture")

        # 2. upsert user
        existing = await self.user_repo.get_by_google_id(google_id)
        if existing:
            await self.user_repo.update_last_login(google_id, name=name, avatar_url=avatar_url)
            user_id = existing["id"]
            # 老用户：如果传了 lang 且与 DB 不同 → UPDATE（PUT 失败的保底）
            if default_lang and default_lang != (existing.get("default_lang") or ""):
                await self.user_repo.update_default_lang(user_id, default_lang)
                logger.info(f"User lang corrected on login: id={user_id}, {existing.get('default_lang')} -> {default_lang}")
            else:
                default_lang = existing.get("default_lang")
            logger.info(f"User logged in: id={user_id}, email={email}")
        else:
            user_id = await self.user_repo.create(google_id, email=email, name=name, avatar_url=avatar_url,
                                                   default_lang=default_lang)
            logger.info(f"User registered: id={user_id}, email={email}")

        # 3. 签发 JWT
        access_token = create_token(user_id=user_id, email=email, default_lang=default_lang)

        return {
            "access_token": access_token,
            "user": {
                "id": user_id,
                "name": name,
                "email": email,
                "avatar_url": avatar_url,
            },
        }
