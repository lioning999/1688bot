"""JWT 认证中间件 — PROTECTED_PREFIXES + EXEMPT_PATHS 模式。"""

from typing import Awaitable, Callable
from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from utils.jwt import decode_token


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """JWT 认证中间件。

    特性：
    - PROTECTED_PREFIXES: 需要认证的路径前缀
    - EXEMPT_PATHS: 保护前缀下的免认证路径
    - 认证成功 → 注入 request.state.user_id
    - 认证失败 → 返回 401 JSON
    """

    PROTECTED_PREFIXES = ["/api/"]
    EXEMPT_PATHS = [
        "/api/auth/google/login",
        "/google-callback",
        "/docs",
        "/openapi.json",
        "/health",
    ]
    EXEMPT_PREFIXES = [
        "/api/analyze",  # 搜索 API 整体豁免（未登录用户也可搜索）
        "/api/config",   # 公开配置（汇率等，无需登录）
        "/api/proxy",    # 图片代理（html2canvas 截图用，无需登录）
        "/api/quota",    # 配额查询（前端未登录时也会调，无敏感数据）
        "/api/admin",    # 管理后台（独立 role=admin 鉴权，不走普通 JWT）
    ]

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ):
        path = request.url.path

        # 提取 token（如有）
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.removeprefix("Bearer ") if auth_header.startswith("Bearer ") else ""

        if self._needs_auth(path):
            # 强制认证：无 token 或 token 无效 → 401
            if not token:
                return JSONResponse(
                    status_code=401,
                    content={"code": 401, "data": None, "message": "缺少认证信息",
                             "msg_code": "MISSING_AUTH"},
                )
            try:
                payload = decode_token(token)
            except Exception:
                return JSONResponse(
                    status_code=401,
                    content={"code": 401, "data": None, "message": "token无效或已过期",
                             "msg_code": "TOKEN_INVALID"},
                )
            request.state.user_id = payload.get("user_id")
        elif token:
            # 可选认证：有 token 就解，不强制；解失败不报错
            try:
                payload = decode_token(token)
                request.state.user_id = payload.get("user_id")
            except Exception:
                pass

        return await call_next(request)

    def _needs_auth(self, path: str) -> bool:
        if path in self.EXEMPT_PATHS:
            return False
        if any(path.startswith(p) for p in self.EXEMPT_PREFIXES):
            return False
        return any(path.startswith(prefix) for prefix in self.PROTECTED_PREFIXES)
