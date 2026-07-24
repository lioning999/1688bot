"""认证 API — Google OAuth 登录。"""

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from adapters.google_auth import google_auth_adapter
from repositories.user_repo import UserRepository
from services.auth_svc import AuthService
from utils.exceptions import ExternalServiceError
from utils.logger import get_logger

logger = get_logger(__name__)

# ---- 依赖 ----
user_repo = UserRepository()
auth_service = AuthService(google_auth=google_auth_adapter, user_repo=user_repo)

# ---- 路由 ----
# /api/auth/* 路由（JWT 中间件豁免登录检查）
auth_router = APIRouter(prefix="/api/auth", tags=["auth"])

# /google-callback 路由（无前缀，Google 回调固定路径）
callback_router = APIRouter(tags=["auth-callback"])


@auth_router.get("/google/login")
async def google_login(redirect: str = ""):
    """跳转到 Google OAuth 授权页。

    可选 redirect 参数指定登录完成后返回的页面路径（通过 Google state 参数透传）。
    仅允许相对路径（以 / 开头且不含 ://），防止 Open Redirect 攻击（Bug #11）。
    """
    if redirect and (not redirect.startswith("/") or "://" in redirect):
        logger.warning(f"Blocked open redirect attempt: {redirect}")
        redirect = ""
    url = google_auth_adapter.get_auth_url(state=redirect)
    return RedirectResponse(url=url, status_code=302)


@callback_router.get("/google-callback")
async def google_callback(code: str, state: str = ""):
    """Google OAuth 回调。

    Google 授权后回调此端点，附带一次性 authorization code。
    后端用 code 换 id_token → upsert user → 签发 JWT → 重定向。
    若 state 参数非空（由 /api/auth/google/login?redirect=xxx 设置），
    登录后重定向到 state 指定的路径而非首页。
    """
    try:
        result = await auth_service.login_with_google(code)
    except ExternalServiceError:
        # 登录失败 → 重定向（state 已含前导 /，如 /report.html?offerId=xxx）
        fallback = state if state else "/"
        return RedirectResponse(url=fallback, status_code=302)

    token = result["access_token"]
    base_url = state if state else "/"
    sep = "&" if "?" in base_url else "?"
    redirect_url = f"{base_url}{sep}token={token}"
    return RedirectResponse(url=redirect_url, status_code=302)
