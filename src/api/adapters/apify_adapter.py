"""Apify 1688 Wholesale Scraper 适配器 — 封装 ApifyClientAsync SDK。

覆盖风险清单：
  #3  90s 超时 → wait_duration=timedelta(seconds=Config.APIFY_WAIT_SECONDS)
"""

import time
from typing import Any
from datetime import timedelta

from apify_client import ApifyClientAsync
from apify_client.errors import ApifyApiError

from config import Config
from domain.urls import extract_offer_id
from utils.exceptions import ExternalServiceError
from utils.logger import get_logger

logger = get_logger(__name__)

# 全局 Apify 调用计数器（进程级，重启清零）
_apify_call_count: int = 0


def get_apify_call_count() -> int:
    """返回 Apify 累计调用次数。"""
    return _apify_call_count


class ApifyAdapter:
    """Apify 1688 Wholesale Scraper 适配器。

    使用官方 ApifyClientAsync SDK：
    actor.call(run_input, wait_duration) → 启动 run + 等待完成 → 取 dataset items。

    ApifyClientAsync v3.x 不支持 async with，直接实例化使用。
    内部 httpx 客户端随对象生命周期管理。
    """

    def __init__(self, token: str = ""):
        self.token = token or Config.APIFY_TOKEN  # 默认 token，向后兼容
        self.tokens = Config.APIFY_TOKENS          # 多 token 列表

    async def fetch_product_by_url(self, url: str) -> dict[str, Any] | None:
        """根据 1688 商品链接获取结构化数据。

        多 token 自动切换：一个 token 配额耗尽 → 自动尝试下一个。

        Args:
            url: 1688 商品详情页完整 URL

        Returns:
            商品数据 dict（dataset 第一条），商品不存在时返回 None

        Raises:
            ExternalServiceError: 配额耗尽 (reason="quota_exhausted") 或 API 异常
        """
        offer_id = extract_offer_id(url)
        if not offer_id:
            logger.warning(f"无法从 URL 提取 offerId: {url[:80]}")
            return None

        last_error: Exception | None = None
        quota_exhausted = False
        tokens = self.tokens if self.tokens else [self.token]

        for i, token in enumerate(tokens):
            if not token:
                continue
            client = ApifyClientAsync(token=token)
            t_token = time.time()

            try:
                global _apify_call_count
                _apify_call_count += 1
                logger.info(f"[Apify] 调用 #{_apify_call_count} offer_id={offer_id} token={i+1}/{len(tokens)} timeout={Config.APIFY_WAIT_SECONDS}s")
                run = await client.actor(Config.APIFY_ACTOR_ID).call(
                    run_input={"offerIds": [offer_id]},
                    wait_duration=timedelta(seconds=Config.APIFY_WAIT_SECONDS),
                )
                t_run = time.time()
                logger.info(f"[Apify] actor.call 完成 offer_id={offer_id} token={i+1} 耗时={t_run - t_token:.1f}s")

                if run is None:
                    logger.warning(f"[Apify] run 返回 None: offer_id={offer_id}")
                    continue

                # 检测 run 级别的配额耗尽（Apify 免费额度用完时 run 成功但 status_message 说明原因）
                status_msg = (getattr(run, "status_message", "") or "").lower()
                if "free runs" in status_msg or "all 25" in status_msg:
                    logger.warning(f"[Apify] token {i+1}/{len(tokens)} 配额耗尽 (run status): {status_msg[:100]}")
                    quota_exhausted = True
                    continue

                page = await client.dataset(run.default_dataset_id).list_items(limit=1)
                items: list[dict[str, Any]] = page.items
                t_dataset = time.time()

                if not items:
                    logger.warning(f"[Apify] dataset 为空: offer_id={offer_id} 耗时 total={t_dataset - t_token:.1f}s")
                    return None  # 商品不存在或数据为空

                # 检测 item 级别的配额耗尽标记
                if len(items) == 1 and items[0].get("limit_reached"):
                    logger.warning(f"[Apify] token {i+1}/{len(tokens)} 配额耗尽 (item flag)，切换下一个")
                    quota_exhausted = True
                    continue

                # 记录响应概要：顶层 key 数量 + 关键字段是否存在
                raw = items[0]
                key_count = len(raw)
                has_price = bool(raw.get("priceInfo"))
                has_sku = bool(raw.get("skuProps"))
                logger.info(
                    f"[Apify] ✓ 成功 #{_apify_call_count} offer_id={offer_id} token={i+1}/{len(tokens)} "
                    f"耗时 total={t_dataset - t_token:.1f}s run={t_run - t_token:.1f}s dataset={t_dataset - t_run:.1f}s "
                    f"响应keys={key_count} 有价格={has_price} 有SKU={has_sku}"
                )
                return raw

            except ApifyApiError as e:
                t_fail = time.time()
                logger.error(
                    f"[Apify] ✗ API异常 token={i+1} offer_id={offer_id} "
                    f"耗时={t_fail - t_token:.1f}s status={getattr(e, 'status_code', '?')} error={e}"
                )
                last_error = e
                continue

        if last_error:
            raise ExternalServiceError(service_name="Apify", details={"offer_id": offer_id}) from last_error
        if quota_exhausted:
            raise ExternalServiceError(
                service_name="Apify",
                details={"offer_id": offer_id, "reason": "quota_exhausted"},
            )
        logger.warning(f"Apify 无结果（可能已下架）: offer_id={offer_id}")
        return None


# 模块级单例
apify_adapter = ApifyAdapter()
