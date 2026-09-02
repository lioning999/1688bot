"""Telegram bot 主进程 — 长轮询 getUpdates + 消息分发。

零新增依赖：直接调 Telegram Bot API（httpx 长轮询），手动 offset。
报告 = 2 条消息自动连发：第 1 条 sendPhoto（图+核心结论），第 2 条 sendMessage（完整验证）。
菜单 = reply keyboard 常驻 + 报告底部 inline 按钮（callback_query 分发）。
收到 409 冲突自动退避；sendMessage/Photo 失败自动降级。
"""

import asyncio
import json
import logging
import re
from typing import Any, cast
from urllib.parse import quote

import httpx

from backend import BackendClient
from bot_config import Config
from i18n import t
from render import render_card, render_product, render_supplier

_OFFER_RE = re.compile(r"1688\.com/offer/(\d+)")
_HTML_TAG_RE = re.compile(r"<[^>]+>")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("sourcely-bot")


def _mk_inline(item_url: str, sample: bool = False) -> dict[str, Any]:
    """报告底部 inline 按钮：查看商品（url 按钮）+ 可选拿样品（callback）。"""
    row: list[dict[str, str]] = []
    if item_url:
        row.append({"text": t("report.open"), "url": item_url})
    if sample:
        row.append({"text": t("report.sample"), "callback_data": "sample"})
    return {"inline_keyboard": [row]} if row else {}


def _mk_menu() -> dict[str, Any]:
    """底部常驻 reply keyboard 菜单（查供应商 + PRO 付费入口，简洁两键）。"""
    return {
        "keyboard": [
            [{"text": t("menu.check")}, {"text": t("menu.pro")}],
        ],
        "resize_keyboard": True,
    }


class TelegramBot:
    _API = "https://api.telegram.org/bot{token}"

    def __init__(self) -> None:
        self.token = Config.TELEGRAM_BOT_TOKEN
        self.backend = BackendClient()
        self._offset = 0

    # ---- Telegram API ----

    async def _request(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = self._API.format(token=self.token) + "/" + method
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            try:
                return resp.json()
            except ValueError:
                return {}

    async def send(self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        resp = await self._request("sendMessage", payload)
        if not resp.get("ok"):
            logger.warning(f"sendMessage HTML 失败: {resp.get('description')} — 降级纯文本")
            payload.pop("parse_mode", None)
            payload["text"] = _HTML_TAG_RE.sub("", text)[:4000]
            resp2 = await self._request("sendMessage", payload)
            if not resp2.get("ok"):
                logger.error(f"sendMessage 纯文本失败: {resp2.get('description')}")

    async def send_photo(self, chat_id: int, caption: str, photo_bytes: bytes, reply_markup: dict[str, Any] | None = None) -> bool:
        """sendPhoto 文件上传（图已由 _fetch_image 拉好）。caption 超 1024 自动截断。"""
        url = self._API.format(token=self.token) + "/sendPhoto"
        data: dict[str, Any] = {"chat_id": chat_id, "caption": caption[:1024], "parse_mode": "HTML"}
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, data=data, files={"photo": ("img.jpg", photo_bytes, "image/jpeg")})
        try:
            ok = bool(resp.json().get("ok"))
        except ValueError:
            ok = False
        if not ok:
            logger.warning(f"sendPhoto 失败: {resp.text[:200]}")
        return ok

    async def _fetch_image(self, img_url: str) -> bytes | None:
        """经后端 /api/proxy/image 拉图（免鉴权、带 Referer 防盗链）。失败返回 None。"""
        proxy_url = Config.BOT_API_BASE.rstrip("/") + "/api/proxy/image?url=" + quote(img_url, safe="")
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(proxy_url)
                if resp.status_code == 200 and resp.content:
                    return resp.content
        except httpx.HTTPError as exc:
            logger.warning(f"图片拉取失败: {img_url[:80]} — {exc}")
        return None

    # ---- 长轮询 ----

    async def poll(self) -> None:
        payload: dict[str, Any] = {"timeout": Config.POLL_TIMEOUT, "allowed_updates": ["message", "callback_query"]}
        if self._offset:
            payload["offset"] = self._offset
        data = await self._request("getUpdates", payload)
        if not data.get("ok"):
            logger.warning(f"getUpdates 失败: {data.get('description', data)}")
            await asyncio.sleep(5)
            return
        for update in data.get("result", []):
            self._offset = int(update["update_id"]) + 1  # 先 ack 再处理（at-most-once）
            try:
                if update.get("message"):
                    await self._handle_message(update["message"])
                elif update.get("callback_query"):
                    await self._handle_callback(update["callback_query"])
            except Exception:
                logger.exception("handle 失败")

    # ---- 消息分发 ----

    async def _handle_message(self, message: dict[str, Any]) -> None:
        chat_id = int(message["chat"]["id"])
        user: dict[str, Any] = message.get("from") or {}
        tg_uid = str(user.get("id", chat_id))
        text = str(message.get("text") or "").strip()

        # reply keyboard 菜单按钮（点击是普通消息，不是 callback）
        if text == t("menu.check"):
            await self.send(chat_id, t("help"))
            return
        if text == t("menu.sample"):
            await self.send(chat_id, t("sample_pending"))
            return
        if text == t("menu.pro"):
            await self._send_pro(chat_id, tg_uid)
            return
        if text == t("menu.help"):
            await self.send(chat_id, t("help"))
            return

        if text.startswith("/start"):
            await self.send(chat_id, t("welcome"), reply_markup=_mk_menu())
            return

        m = _OFFER_RE.search(text)
        if not m:
            await self.send(chat_id, t("no_link"))
            return
        url = _extract_url(text, m.start(), m.end())
        await self.send(chat_id, t("analyzing"))
        await self._run_analysis(chat_id, tg_uid, url)

    # ---- callback（报告底部按钮） ----

    async def _handle_callback(self, cq: dict[str, Any]) -> None:
        chat_id = int(cq["message"]["chat"]["id"])
        data = str(cq.get("data") or "")
        if data == "sample":
            await self.send(chat_id, t("sample_pending"))
        await self._request("answerCallbackQuery", {"callback_query_id": cq["id"]})

    # ---- 分析闭环（2 条消息自动连发） ----

    async def _run_analysis(self, chat_id: int, tg_uid: str, url: str) -> None:
        code, data = await self.backend.analyze_start(tg_uid, url)
        task_id = data.get("data", {}).get("task_id", "") if data else ""
        if code != 200 or not task_id:
            await self._send_backend_error(chat_id, data)
            return

        waited = 0
        while waited < Config.ANALYZE_MAX_WAIT:
            await asyncio.sleep(Config.ANALYZE_POLL_INTERVAL)
            waited += Config.ANALYZE_POLL_INTERVAL
            code, data = await self.backend.analyze_poll(tg_uid, task_id)
            if code != 200:
                await self._send_backend_error(chat_id, data)
                return
            task = cast(dict[str, Any], data.get("data") or {})
            status = task.get("status")
            if status == "done":
                result = cast(dict[str, Any], task.get("result") or {})
                display = cast(dict[str, Any], result.get("display") or {})
                await self._send_report(chat_id, display)
                return
            if status == "failed":
                await self._send_backend_error(chat_id, task)
                return

        await self.send(chat_id, t("analyze_timeout", n=Config.ANALYZE_MAX_WAIT))

    async def _send_report(self, chat_id: int, display: dict[str, Any]) -> None:
        """3 条自动连发：① 综合卡 sendPhoto（图失败降级文本）→ ② 产品验证 → ③ 供应商验证。逐条失败隔离。"""
        item_url = str(display.get("itemUrl") or "")
        card = render_card(display)
        product = render_product(display)
        supplier = render_supplier(display)
        images = cast(list[Any], display.get("images") or [])
        img_url = str(images[0]) if images else ""

        # 第 1 条：产品图 + 核心结论（挂 [查看商品]）
        markup1 = _mk_inline(item_url) or None
        sent_photo = False
        if img_url:
            img = await self._fetch_image(img_url)
            if img:
                sent_photo = await self.send_photo(chat_id, card, img, markup1)
        if not sent_photo:
            await self.send(chat_id, card, markup1)  # 降级：纯文本卡片，内容不丢

        # 第 2、3 条：产品验证 / 供应商验证（挂 [查看商品][拿样品]），逐条失败隔离
        markup2 = _mk_inline(item_url, sample=True) or None
        for part in (product, supplier):
            if not part:
                continue
            await asyncio.sleep(0.5)  # 防粘包，独立通知
            try:
                await self.send(chat_id, part, markup2)
            except Exception:
                logger.exception("验证消息发送失败，跳过本条")

    async def _send_pro(self, chat_id: int, tg_uid: str) -> None:
        """PRO 菜单：显示当前配额 + 开通引导（阶段 3 接付款）。"""
        quota = await self.backend.quota(tg_uid)
        if quota is not None:
            await self.send(chat_id, t("pro_status", n=quota))
        else:
            await self.send(chat_id, t("pro_status_err"))

    async def _send_backend_error(self, chat_id: int, data: dict[str, Any]) -> None:
        """后端错误 → msg_code → ru 文案；无翻译降级内部错误提示。"""
        msg_code = str(data.get("msg_code") or data.get("error_msg_code") or "")
        text = t(f"msg.{msg_code}") if msg_code else ""
        if not text or text == f"msg.{msg_code}":
            text = t("internal_error")
        await self.send(chat_id, text)


def _extract_url(text: str, start: int, end: int) -> str:
    """截取 1688 链接完整 URL（含查询参数），向两边扩展到空白边界。"""
    i = start
    while i > 0 and not text[i - 1].isspace():
        i -= 1
    j = end
    while j < len(text) and not text[j].isspace():
        j += 1
    return text[i:j]


async def main() -> None:
    Config.validate()
    bot = TelegramBot()
    logger.info(f"Sourcely bot 启动: api={Config.BOT_API_BASE}")
    while True:
        try:
            await bot.poll()
        except httpx.HTTPError as exc:
            logger.warning(f"轮询网络错误: {exc}")
            await asyncio.sleep(5)
        except Exception:
            logger.exception("轮询未知错误")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
