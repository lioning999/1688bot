"""后端 HTTP 客户端 — bot 只走 HTTP 调 src/api，不碰 DB。

JWT 缓存：内存缓存 telegram_uid → access_token；收到 401 自动重登录一次。
secret 恒时比较在后端做，本进程只负责带上 secret 换 JWT。
"""

import time
from typing import Any, Awaitable, Callable

import httpx

from bot_config import Config

_AuthCall = Callable[[str], Awaitable[tuple[int, dict[str, Any]]]]


class BackendClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(base_url=Config.BOT_API_BASE, timeout=30.0)
        self._tokens: dict[str, tuple[str, float]] = {}  # telegram_uid → (jwt, 过期时间戳)

    # ---- 底层请求 ----

    async def _post(self, path: str, json_body: dict[str, Any], headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
        return await self._json(path, json_body, headers, is_post=True)

    async def _get(self, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
        return await self._json(path, None, headers, is_post=False)

    async def _json(self, path: str, json_body: dict[str, Any] | None, headers: dict[str, str] | None, is_post: bool) -> tuple[int, dict[str, Any]]:
        try:
            resp = await (self._client.post(path, json=json_body, headers=headers) if is_post
                          else self._client.get(path, headers=headers))
            return resp.status_code, (resp.json() if resp.content else {})
        except httpx.HTTPError as exc:
            return 0, {"msg_code": "", "message": f"backend request failed: {exc}"}

    # ---- 登录 + JWT 缓存 ----

    async def login(self, telegram_uid: str) -> str:
        code, data = await self._post("/api/bot/login", {
            "telegram_uid": telegram_uid,
            "secret": Config.BOT_SECRET,
        })
        token = data.get("data", {}).get("access_token", "") if data else ""
        if code != 200 or not token:
            raise RuntimeError(f"bot login failed: code={code} msg={data.get('message') if data else ''}")
        self._tokens[telegram_uid] = (token, time.time() + 3600 * 24 * 89)  # JWT 90 天，缓存 89 天提前换
        return token

    async def get_token(self, telegram_uid: str) -> str:
        cached = self._tokens.get(telegram_uid)
        if cached and cached[1] > time.time():
            return cached[0]
        return await self.login(telegram_uid)

    async def _with_auth(self, telegram_uid: str, call: _AuthCall) -> tuple[int, dict[str, Any]]:
        """带 Bearer JWT 调 call(jwt)；401 → 重登录一次重试。"""
        token = await self.get_token(telegram_uid)
        code, data = await call(token)
        if code == 401:
            token = await self.login(telegram_uid)
            code, data = await call(token)
        return code, data

    # ---- 业务调用 ----

    async def analyze_start(self, telegram_uid: str, url: str) -> tuple[int, dict[str, Any]]:
        async def _call(jwt: str) -> tuple[int, dict[str, Any]]:
            return await self._post("/api/analyze", {"url": url, "lang": "ru"},
                                    {"Authorization": f"Bearer {jwt}"})
        return await self._with_auth(telegram_uid, _call)

    async def analyze_poll(self, telegram_uid: str, task_id: str) -> tuple[int, dict[str, Any]]:
        async def _call(jwt: str) -> tuple[int, dict[str, Any]]:
            return await self._get(f"/api/analyze/{task_id}", {"Authorization": f"Bearer {jwt}"})
        return await self._with_auth(telegram_uid, _call)

    async def history(self, telegram_uid: str) -> tuple[int, dict[str, Any]]:
        """拉当前用户历史记录（后端已按 tier 截断 20/100，含非 zh 展示标题）。"""
        async def _call(jwt: str) -> tuple[int, dict[str, Any]]:
            return await self._get("/api/history", {"Authorization": f"Bearer {jwt}"})
        return await self._with_auth(telegram_uid, _call)

    async def report(self, telegram_uid: str, offer_id: str) -> tuple[int, dict[str, Any]]:
        """拉某 offer 已保存的 ru 报告 display（复用后端 display_i18n，不重抓）。"""
        async def _call(jwt: str) -> tuple[int, dict[str, Any]]:
            return await self._get(f"/api/report/{offer_id}?lang=ru",
                                   {"Authorization": f"Bearer {jwt}"})
        return await self._with_auth(telegram_uid, _call)

    async def quota(self, telegram_uid: str) -> int | None:
        async def _call(jwt: str) -> tuple[int, dict[str, Any]]:
            return await self._get("/api/quota", {"Authorization": f"Bearer {jwt}"})
        code, data = await self._with_auth(telegram_uid, _call)
        if code == 200 and data.get("data"):
            try:
                return int(data["data"].get("remaining", 0))
            except (TypeError, ValueError):
                return None
        return None
