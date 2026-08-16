"""Qwen3-Flash API 适配器 — 封装 HTTP 调用。

纯 HTTP 封装，不含业务逻辑（prompt 构建、响应校验均在调用方）。
"""

from typing import Any

import httpx

from config import Config
from utils.logger import get_logger

logger = get_logger(__name__)


class QwenAdapter:
    """Qwen3-Flash API 适配器。

    封装 HTTP 调用、超时、错误处理。prompt 构建和响应校验由调用方负责。
    """

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        api_key: str = "",
        api_base: str = "",
        timeout: float = 20.0,
    ) -> dict[str, Any] | None:
        """调用 Qwen chat/completions API。

        Args:
            messages: OpenAI 兼容格式的消息列表
            model: 模型名（空则用 Config.QWEN_MODEL）
            api_key: API Key（空则用 Config.QWEN_API_KEY）
            api_base: API Base URL（空则用 Config.QWEN_API_BASE）
            timeout: 超时秒数

        Returns:
            API 响应 JSON dict，失败返回 None
        """
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{api_base or Config.QWEN_API_BASE}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key or Config.QWEN_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model or Config.QWEN_MODEL,
                        "messages": messages,
                        "temperature": Config.QWEN_TEMPERATURE,
                        "max_tokens": Config.QWEN_MAX_TOKENS,
                    },
                )

            if resp.status_code != 200:
                logger.warning(f"[Qwen] API error {resp.status_code}: {resp.text[:200]}")
                return None

            body: dict[str, Any] = resp.json()
            usage: dict[str, Any] = body.get("usage", {})  # type: ignore[reportUnknownVariableType]
            choice: dict[str, Any] = body.get("choices", [{}])[0]  # type: ignore[reportUnknownVariableType]
            finish: str = choice.get("finish_reason", "unknown")  # type: ignore[reportUnknownVariableType]
            logger.info(
                f"[Qwen] 调用成功 model={model or Config.QWEN_MODEL} "
                f"tokens in={usage.get('prompt_tokens','?')} out={usage.get('completion_tokens','?')} "
                f"finish={finish}"
            )
            return body

        except httpx.TimeoutException:
            logger.warning("Qwen API timeout")
            return None
        except Exception:
            logger.exception("Qwen API unexpected error")
            return None


# 模块级单例
qwen_adapter = QwenAdapter()
