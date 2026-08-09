"""认证 API — Google OAuth 登录。"""

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from config import Config
from services.auth_svc import AuthService
from utils.exceptions import ExternalServiceError
from utils.logger import get_logger

logger = get_logger(__name__)

# ---- 依赖 ----
auth_service = AuthService()

# ---- 路由 ----
# /api/auth/* 路由（JWT 中间件豁免登录检查）
auth_router = APIRouter(prefix="/api/auth", tags=["auth"])

# /google-callback 路由（无前缀，Google 回调固定路径）
callback_router = APIRouter(tags=["auth-callback"])


@auth_router.get("/google/login")
async def google_login(redirect: str = "", platform: str = ""):
    """跳转到 Google OAuth 授权页。

    - redirect: Web 登录完成后返回的页面路径（如 /history）
    - platform: "extension" 时走 Chrome 插件流程（回调到 chromiumapp.org）

    仅允许相对路径（以 / 开头且不含 ://），防止 Open Redirect 攻击（Bug #11）。
    """
    # 路径白名单，拒绝 //evil.com 协议相对 URL 绕过（Bug #11 强化）
    ALLOWED_REDIRECT_PATHS = {"/", "/history", "/help"}
    if redirect:
        if redirect not in ALLOWED_REDIRECT_PATHS:
            logger.warning(f"Blocked open redirect attempt: {redirect}")
            redirect = ""
    # 构造 state：插件流用 "extension"，Web 流用 redirect 路径
    if platform == "extension":
        state = "extension"
    else:
        state = redirect
    url = auth_service.get_auth_url(state=state)
    return RedirectResponse(url=url, status_code=302)


@callback_router.get("/google-callback")
async def google_callback(code: str | None = None, state: str = "",
                           error: str | None = None):
    """Google OAuth 回调。

    Google 授权后回调此端点，附带一次性 authorization code。
    后端用 code 换 id_token → upsert user → 签发 JWT → 重定向。
    若 state 参数非空（由 /api/auth/google/login?redirect=xxx 设置），
    登录后重定向到 state 指定的路径而非首页。

    Google 在用户拒绝授权或出错时回调 ?error=access_denied，
    此时 code 为空 → 直接跳错误页，不抛 422。
    """
    if error or not code:
        reason = error or "no_code"
        logger.warning(f"[Auth] Google 回调缺少 code: reason={reason} state={state}")
        if state == "extension":
            ext_id = Config.CHROME_EXTENSION_ID
            return RedirectResponse(url=f"https://{ext_id}.chromiumapp.org/?error=auth_failed", status_code=302)
        return RedirectResponse(url="/?error=auth_failed", status_code=302)
    try:
        result = await auth_service.login_with_google(code)
        logger.info(f"[Auth] Google 回调成功 user_id={result['user']['id']} state={state}")
    except ExternalServiceError as e:
        logger.warning(f"[Auth] Google 回调失败: {e} state={state}")
        if state == "extension":
            ext_id = Config.CHROME_EXTENSION_ID
            return RedirectResponse(url=f"https://{ext_id}.chromiumapp.org/?error=auth_failed", status_code=302)
        return RedirectResponse(url="/?error=auth_failed", status_code=302)

    token = result["access_token"]
    # 插件流 → 302 到 chromiumapp.org（Chrome 拦截，不会真发网络请求）
    if state == "extension":
        ext_id = Config.CHROME_EXTENSION_ID
        redirect_url = f"https://{ext_id}.chromiumapp.org/?token={token}"
        return RedirectResponse(url=redirect_url, status_code=302)
    # Web 流 → 302 到首页（cookie 传 token）
    base_url = state if state else "/"
    resp = RedirectResponse(url=base_url, status_code=302)
    # JWT 通过 cookie 传递，不再进 URL（防止被反向代理日志记录）
    resp.set_cookie(
        key="sourcely_token", value=token,
        max_age=Config.JWT_EXPIRE_MINUTES * 60,
        httponly=False,  # JS 需读取后转存 sessionStorage
        secure=False,    # 开发环境 HTTP，生产应改为 True
        samesite="lax",
    )
    return resp
