"""认证服务 — Google OAuth 登录/注册业务编排。"""

from datetime import date
from typing import Any

from adapters.google_auth import GoogleAuthAdapter
from config import Config
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

    async def bot_login(self, telegram_uid: str) -> dict[str, Any]:
        """Telegram bot 自动注册/登录（零密码，telegram_uid 唯一身份，语言固定 ru）。

        首触建用户（quota = DAILY_FREE_QUOTA），复用现有 JWT 签发。
        """
        default_lang = "ru"  # bot 仅俄语市场
        existing = await self.user_repo.get_by_telegram_uid(telegram_uid)
        if existing:
            user_id = existing["id"]
        else:
            user_id = await self.user_repo.create_by_telegram(telegram_uid, default_lang=default_lang)
            logger.info(f"Bot user registered: id={user_id}, telegram_uid={telegram_uid}")

        access_token = create_token(user_id=user_id, default_lang=default_lang)
        return {"access_token": access_token, "user": {"id": user_id}}

    async def get_quota_with_reset(self, user_id: int) -> dict[str, Any] | None:
        """查配额 + 懒重置补地板。None = 用户不存在。

        从 routes 下沉（原 analyze.py 配额判断），供 POST /api/analyze 与 GET /api/quota 共用。
        """
        user_quota = await self.user_repo.get_quota_info(user_id)
        if not user_quota:
            return None
        quota = user_quota["quota"]
        tier = str(user_quota.get("tier", "free"))
        last_reset_date = user_quota.get("last_reset_date")
        daily_floor = Config.DAILY_PAID_QUOTA if tier == "paid" else Config.DAILY_FREE_QUOTA
        today = date.today()
        if last_reset_date is None or last_reset_date < today:
            quota = await self.user_repo.lazy_reset_daily_quota(user_id, tier, daily_floor)
        return {
            "remaining": quota,
            "daily_limit": daily_floor,
            "tier": tier,
            "history_max": Config.HISTORY_PAID_MAX if tier == "paid" else Config.HISTORY_FREE_MAX,
        }

    async def update_default_lang(self, user_id: int, lang: str) -> None:
        """更新用户默认语言（从 routes 下沉）。"""
        await self.user_repo.update_default_lang(user_id, lang)


# 模块级单例 — routes 层共享，不再各自 new UserRepository
auth_service = AuthService()
