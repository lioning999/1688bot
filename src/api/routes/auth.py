"""认证 API — Google OAuth 登录。"""

import re
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from config import Config
from services.auth_svc import auth_service
from utils.exceptions import ExternalServiceError
from utils.logger import get_logger

logger = get_logger(__name__)

# ---- 依赖 ----
# auth_service 由 services.auth_svc 模块级单例提供（import 引入）

# ---- 路由 ----
# /api/auth/* 路由（JWT 中间件豁免登录检查）
auth_router = APIRouter(prefix="/api/auth", tags=["auth"])

# /google-callback 路由（无前缀，Google 回调固定路径）
callback_router = APIRouter(tags=["auth-callback"])

# /api/user/* 路由（需 JWT 认证）
user_router = APIRouter(prefix="/api/user", tags=["user"])

# Chrome 扩展 ID 固定 32 位小写 a-p；非法回落默认 ID，防 Open Redirect（Bug #11 插件流）
_EXT_ID_PATTERN = re.compile(r"[a-p]{32}")


def _sanitize_ext_id(ext_id: str) -> str:
    """校验 ext_id 为合法 Chrome 扩展 ID；空原样返回（Web 流），非法回落默认 ID。"""
    if not ext_id:
        return ext_id
    return ext_id if _EXT_ID_PATTERN.fullmatch(ext_id) else Config.CHROME_EXTENSION_ID


@auth_router.get("/google/login")
async def google_login(redirect: str = "", platform: str = "", ext_id: str = "",
                        lang: str = ""):
    """跳转到 Google OAuth 授权页。

    - redirect: Web 登录完成后返回的页面路径（如 /history）
    - platform: "extension" 时走 Chrome 插件流程（回调到 chromiumapp.org）
    - ext_id: Chrome 插件 ID（本地开发 ID 不固定，由 service worker 动态传入）
    - lang: 插件当前语言（首次登录写入 default_lang，后续登录用于比对纠正）

    仅允许相对路径（以 / 开头且不含 ://），防止 Open Redirect 攻击（Bug #11）。
    """
    # 路径白名单，拒绝 //evil.com 协议相对 URL 绕过（Bug #11 强化）
    ALLOWED_REDIRECT_PATHS = {"/", "/history", "/help"}
    if redirect:
        if redirect not in ALLOWED_REDIRECT_PATHS:
            logger.warning(f"Blocked open redirect attempt: {redirect}")
            redirect = ""
    # 构造 state：插件流用 "extension:{ext_id}:lang:{lang}"，Web 流用 redirect 路径
    if platform == "extension":
        parts = ["extension", _sanitize_ext_id(ext_id) or Config.CHROME_EXTENSION_ID]
        if lang:
            parts.append("lang")
            parts.append(lang)
        state = ":".join(parts)
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
    # 解析 state 提取 ext_id 和 lang
    # 格式: "extension:{ext_id}" (旧) 或 "extension:{ext_id}:lang:{lang}" (新)
    def _parse_state(s: str) -> tuple[str, str]:
        ext_id = ""
        lang = ""
        if s.startswith("extension:"):
            parts = s.split(":")
            ext_id = parts[1] if len(parts) > 1 else ""
            idx = 2
            while idx < len(parts) - 1:
                if parts[idx] == "lang":
                    lang = parts[idx + 1]
                    break
                idx += 1
        return ext_id, lang

    ext_id, lang = _parse_state(state)
    ext_id = _sanitize_ext_id(ext_id)

    if error or not code:
        reason = error or "no_code"
        logger.warning(f"[Auth] Google 回调缺少 code: reason={reason} state={state}")
        if ext_id:
            return RedirectResponse(url=f"https://{ext_id}.chromiumapp.org/?error=auth_failed", status_code=302)
        return RedirectResponse(url="/?error=auth_failed", status_code=302)
    try:
        result = await auth_service.login_with_google(code, default_lang=lang or None)
        logger.info(f"[Auth] Google 回调成功 user_id={result['user']['id']} lang={lang} state={state}")
    except ExternalServiceError as e:
        logger.warning(f"[Auth] Google 回调失败: {e} state={state}")
        if ext_id:
            return RedirectResponse(url=f"https://{ext_id}.chromiumapp.org/?error=auth_failed", status_code=302)
        return RedirectResponse(url="/?error=auth_failed", status_code=302)

    token = result["access_token"]
    # 插件流 → 302 到 chromiumapp.org（Chrome 拦截，不会真发网络请求）
    if ext_id:
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


# ====================================================================
# PUT /api/user/lang — 更新默认语言
# ====================================================================

@user_router.put("/lang")
async def update_lang(request: Request) -> dict[str, Any]:
    """更新用户默认语言（用户主动切语言时调用）。"""
    user_id: int = getattr(request.state, "user_id", 0) or 0
    body: dict[str, Any] = await request.json()
    lang: str = str(body.get("lang", "")).strip()
    if not lang or lang not in ("en", "vi", "th", "zh", "ru"):
        return {"code": 400, "msg_code": "INVALID_LANG", "data": None, "message": "不支持的语言"}
    await auth_service.update_default_lang(user_id, lang)
    logger.info(f"[User] lang updated: user_id={user_id}, lang={lang}")
    return {"code": 200, "msg_code": "OK", "data": None, "message": "ok"}
