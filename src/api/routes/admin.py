"""Admin 管理后台 — 自用：登录(env账号) + 用户列表 + 会员切换 + 加配额。

鉴权独立于普通用户 JWT：login 校验 env 账号密码 → 签发 role=admin 的短命 token。
所有 /api/admin/* 由 _require_admin 依赖校验，普通用户 token 无效。
管理页 HTML 在 src/admin/admin.html（本文件只读文件返回）。
"""

from datetime import datetime, timedelta, timezone
from hmac import compare_digest
from pathlib import Path
from typing import Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from config import Config
from repositories.user_repo import UserRepository
from utils.logger import get_logger

logger = get_logger(__name__)

# 管理页 HTML 路径：src/admin/admin.html
_ADMIN_HTML_PATH = Path(__file__).resolve().parent.parent.parent / "admin" / "admin.html"

_user_repo = UserRepository()

admin_router = APIRouter(prefix="/api/admin", tags=["admin"])
admin_page_router = APIRouter(tags=["admin-page"])


def _require_admin(request: Request) -> None:
    """校验 Authorization: Bearer <admin token>，非法直接 401。"""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ") if auth_header.startswith("Bearer ") else ""
    if not token:
        raise HTTPException(status_code=401, detail="未授权")
    try:
        payload: dict[str, Any] = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=[Config.JWT_ALGORITHM])
    except Exception:
        raise HTTPException(status_code=401, detail="未授权")
    if payload.get("role") != "admin":
        raise HTTPException(status_code=401, detail="未授权")


@admin_router.post("/login")
async def admin_login(request: Request) -> dict[str, Any]:
    """账号密码登录（env 配置）。成功返回短命 admin token（默认 12h）。"""
    body: dict[str, Any] = await request.json()
    username: str = str(body.get("username", ""))
    password: str = str(body.get("password", ""))
    if not Config.ADMIN_USERNAME or not Config.ADMIN_PASSWORD:
        logger.warning("[Admin] 登录被拒：env 未配置 ADMIN_USERNAME/PASSWORD")
        return {"code": 401, "data": None, "message": "后台未启用", "msg_code": "ADMIN_NOT_CONFIGURED"}
    if not compare_digest(username, Config.ADMIN_USERNAME) or not compare_digest(password, Config.ADMIN_PASSWORD):
        logger.warning(f"[Admin] 登录失败 username={username}")
        return {"code": 401, "data": None, "message": "账号或密码错误", "msg_code": "ADMIN_LOGIN_FAILED"}
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "role": "admin",
        "iat": now,
        "exp": now + timedelta(hours=Config.ADMIN_TOKEN_EXPIRE_HOURS),
    }
    token = jwt.encode(payload, Config.JWT_SECRET_KEY, algorithm=Config.JWT_ALGORITHM)
    logger.info("[Admin] 登录成功")
    return {"code": 200, "data": {"token": token}, "message": "ok", "msg_code": "OK"}


@admin_router.get("/users")
async def admin_users(_: None = Depends(_require_admin)) -> dict[str, Any]:
    """用户列表：邮箱/语言/会员/配额/注册时间/最后登录。"""
    users = await _user_repo.list_users()
    return {"code": 200, "data": {"users": users}, "message": "ok", "msg_code": "OK"}


@admin_router.post("/users/{user_id}/tier")
async def admin_toggle_tier(user_id: int, _: None = Depends(_require_admin)) -> dict[str, Any]:
    """切换会员等级（free↔paid）。"""
    new_tier = await _user_repo.toggle_tier(user_id)
    if not new_tier:
        return {"code": 404, "data": None, "message": "用户不存在", "msg_code": "USER_NOT_FOUND"}
    logger.info(f"[Admin] 切换会员 user_id={user_id} → {new_tier}")
    return {"code": 200, "data": {"tier": new_tier}, "message": "ok", "msg_code": "OK"}


@admin_router.post("/users/{user_id}/quota")
async def admin_add_quota(user_id: int, request: Request,
                           _: None = Depends(_require_admin)) -> dict[str, Any]:
    """加配额（300/500/1000 由前端选择传入）。"""
    body: dict[str, Any] = await request.json()
    amount: int = int(body.get("amount", 0))
    if amount not in (300, 500, 1000):
        return {"code": 400, "data": None, "message": "配额只能是 300/500/1000", "msg_code": "ADMIN_BAD_QUOTA"}
    new_quota = await _user_repo.add_quota(user_id, amount)
    if new_quota == 0:
        return {"code": 404, "data": None, "message": "用户不存在", "msg_code": "USER_NOT_FOUND"}
    logger.info(f"[Admin] 加配额 user_id={user_id} +{amount} → {new_quota}")
    return {"code": 200, "data": {"quota": new_quota}, "message": "ok", "msg_code": "OK"}


@admin_page_router.get("/admin", response_class=HTMLResponse)
async def admin_page() -> HTMLResponse:
    """管理后台页面（中文单页，读 src/admin/admin.html）。"""
    return HTMLResponse(content=_ADMIN_HTML_PATH.read_text(encoding="utf-8"))
