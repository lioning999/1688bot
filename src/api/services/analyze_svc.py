"""1688 商品分析服务 — 缓存→限流→Apify→判词→入库 全流程编排。

覆盖风险清单：
  #2  请求合并（Coalescing） → _pending 字典
  #3  90s 超时 + 过期缓存兜底
  #7  三级降级响应
  #8  字段级容错（判词引擎 + 映射层均检查字段存在性）
"""

import asyncio
import json
import time
import uuid
from typing import Any

from config import Config
from adapters.apify_adapter import apify_adapter
from domain import cache as analysis_cache
from domain.cache import cache as _cache_store  # 只读过期缓存（风险 #3 #7 降级数据源）
from domain.product_mapper import map_raw
from domain.verdict_engine import judge_all
from repositories.analysis_repo import AnalysisRepository
from utils.exceptions import ExternalServiceError
from utils.logger import get_logger

logger = get_logger(__name__)

# ---- 异步任务管理 ----
_pending: dict[str, asyncio.Task[dict[str, Any]]] = {}  # {offer_id: Task}  请求合并（风险 #2）
_tasks: dict[str, dict[str, Any]] = {}        # {task_id: {status, result, ...}}  异步轮询（风险 #10）
TASK_TTL = Config.TASK_TTL  # 任务结果保留时长（秒）


class AnalyzeService:
    """商品分析编排。依赖注入。"""

    def __init__(self, repo: AnalysisRepository):
        self.repo = repo

    # ------------------------------------------------------------------
    # 公开接口：异步轮询模式（风险 #10）
    # ------------------------------------------------------------------

    async def start(self, offer_id: str, user_id: int = 0, raw_url: str = "") -> str:
        """启动分析，立即返回 task_id。

        后台执行：缓存检查 → 限流 → Apify → 判词 → 入库。
        前端每 2s 轮询 GET /api/analyze/{task_id}。
        """
        # 请求合并（风险 #2）：同一 offer_id 正在分析中 → 等现有结果
        if offer_id in _pending:
            logger.info(f"Request coalesced: offer_id={offer_id}")
            existing_task = _pending[offer_id]
            task_id = str(uuid.uuid4())[:8]
            _tasks[task_id] = {"status": "pending", "result": None, "created_at": time.time()}

            async def _wait_existing():
                try:
                    result = await existing_task
                    _tasks[task_id] = {"status": "done", "result": result, "created_at": time.time()}
                except Exception as e:
                    _tasks[task_id] = {"status": "failed", "error": str(e), "created_at": time.time()}

            asyncio.create_task(_wait_existing())
            return task_id

        task_id = str(uuid.uuid4())[:8]
        _tasks[task_id] = {"status": "pending", "result": None, "created_at": time.time()}
        _pending[offer_id] = asyncio.create_task(self._run(task_id, offer_id, raw_url))
        return task_id

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """查询任务状态。None = 不存在或已过期。"""
        task = _tasks.get(task_id)
        if task and time.time() - task["created_at"] > TASK_TTL:
            del _tasks[task_id]
            return None
        return task

    async def get_history(self, user_id: int, limit: int = 20) -> list[dict[str, Any]]:
        """查用户最近的分析记录（只读 DB，不调 Apify）。"""
        return await self.repo.get_history(user_id, limit)

    async def delete_record(self, analysis_id: int, user_id: int) -> bool:
        """删除一条分析记录。校验归属，删除成功返回 True。"""
        return await self.repo.delete(analysis_id, user_id)

    async def get_saved_report(self, offer_id: str, user_id: int) -> dict[str, Any] | None:
        """从 DB 读已保存的报告（Bug #1：登录用户从历史跳转时秒出，不走 Apify）。"""
        return await self.repo.get_by_offer_id(offer_id, user_id)

    async def save_report(self, user_id: int, offer_id: str) -> dict[str, Any] | None:
        """用户手动保存分析报告到 DB。

        从内存缓存取数据 → 检查 20 条上限 → 调用 repo.upsert() 写入。
        缓存不存在返回 None。已达上限返回 {"limit_exceeded": True}。
        """
        cached = analysis_cache.get(offer_id)
        if cached is None:
            return None

        # 检查 20 条上限（upsert 同一条不拦截）
        count = await self.repo.count_by_user(user_id)
        if count >= 20:
            existing = await self.repo.get_history(user_id, limit=100)
            saved_ids = {r.get("offer_id") for r in existing}
            if str(offer_id) not in saved_ids:
                return {"limit_exceeded": True, "count": count}

        await self._save_to_db_upsert(cached, user_id, offer_id)
        return cached

    # ------------------------------------------------------------------
    # 后台分析流水线
    # ------------------------------------------------------------------

    async def _run(self, task_id: str, offer_id: str, raw_url: str) -> dict[str, Any]:
        """完整分析流水线（在后台 asyncio.Task 中执行）。"""
        try:
            _tasks[task_id]["status"] = "running"

            # ---- 1. 缓存检查（风险 #1） ----
            cached = analysis_cache.get(offer_id)
            if cached:
                logger.info(f"Cache hit: offer_id={offer_id}")
                _tasks[task_id] = {"status": "done", "result": cached, "created_at": time.time()}
                return cached

            # ---- 2. Apify 抓取（风险 #3：90s 超时） ----
            try:
                raw = await apify_adapter.fetch_product_by_url(raw_url or Config.URL_1688_DETAIL.format(offer_id=offer_id))
            except ExternalServiceError as e:
                logger.error(f"Apify fetch failed: {e}")
                is_quota = e.details.get("reason") == "quota_exhausted" if e.details else False
                # 过期缓存兜底（风险 #3 + #7 一级降级）
                expired = _get_expired_cache(offer_id)
                if expired:
                    _tasks[task_id] = {
                        "status": "done", "result": expired,
                        "warning": "数据可能不是最新，今日分析额度已用完" if is_quota else "数据可能不是最新，该链接当前无法获取",
                        "created_at": time.time(),
                    }
                    return expired
                # 无缓存 → 区分错误原因
                if is_quota:
                    _tasks[task_id] = {"status": "failed", "error": "今日分析服务额度已用完，请明天再试", "created_at": time.time()}
                else:
                    _tasks[task_id] = {"status": "failed", "error": "获取失败，请稍后重试。如持续失败请联系客服", "created_at": time.time()}
                raise
            except Exception as e:
                logger.error(f"Apify fetch failed: {e}")
                # 过期缓存兜底（风险 #3 + #7 一级降级）
                expired = _get_expired_cache(offer_id)
                if expired:
                    _tasks[task_id] = {
                        "status": "done", "result": expired,
                        "warning": "数据可能不是最新，该链接当前无法获取",
                        "created_at": time.time(),
                    }
                    return expired
                # 无缓存（风险 #7 三级降级）
                _tasks[task_id] = {"status": "failed", "error": "获取失败，请稍后重试。如持续失败请联系客服", "created_at": time.time()}
                raise ExternalServiceError(service_name="Apify", details={"reason": "fetch_failed"}) from e

            if raw is None:
                expired = _get_expired_cache(offer_id)
                if expired:
                    _tasks[task_id] = {
                        "status": "done", "result": expired,
                        "warning": "数据可能不是最新，该链接当前无法获取",
                        "created_at": time.time(),
                    }
                    return expired
                _tasks[task_id] = {
                    "status": "failed",
                    "error": "该链接可能已下架，请检查后重试",
                    "created_at": time.time(),
                }
                raise ExternalServiceError(service_name="Apify", details={"reason": "empty_result"})

            # ---- 3. 映射 + 判词 ----
            mapped = map_raw(raw, raw_url, offer_id)

            # 判词（风险 #4 #5 #6）
            verdicts = judge_all(mapped)
            mapped["verdict_product"] = verdicts["product"]
            mapped["verdict_factory"] = verdicts["factory"]
            mapped["verdict_sample"] = verdicts["sample"]

            # ---- 4. 写缓存（风险 #1 #14 L2） ----
            analysis_cache.set(offer_id, mapped)

            _tasks[task_id] = {"status": "done", "result": mapped, "created_at": time.time()}
            logger.info(f"Analysis done: offer_id={offer_id} task={task_id}")
            return mapped

        except ExternalServiceError:
            raise
        except Exception as e:
            logger.exception(f"Analysis failed: offer_id={offer_id}")
            _tasks[task_id] = {"status": "failed", "error": "服务器内部错误，请稍后重试", "created_at": time.time()}
            raise ExternalServiceError(service_name="分析引擎") from e
        finally:
            _pending.pop(offer_id, None)

    async def _save_to_db_upsert(self, mapped: dict[str, Any], user_id: int, offer_id: str) -> None:
        """同步写入 analysis 表（用户手动保存，跑 upsert 不报重复键错误）。"""
        await self.repo.upsert(self._db_data(mapped, user_id, offer_id))

    def _db_data(self, mapped: dict[str, Any], user_id: int, offer_id: str) -> dict[str, Any]:
        """提取 DB 写入字段。列字段仅供历史列表快速展示，完整数据在 result_json。"""
        return {
            "user_id": user_id,
            "offer_id": offer_id,
            "status": "done",
            "title": mapped.get("title"),
            "image_url": mapped.get("image"),
            "price_min": mapped.get("priceCNY", {}).get("low") if mapped.get("priceCNY") else None,  # type: ignore[reportUnknownMemberType]
            "price_max": mapped.get("priceCNY", {}).get("high") if mapped.get("priceCNY") else None,  # type: ignore[reportUnknownMemberType]
            "apify_task_id": mapped.get("apify_task_id"),
            "result_json": json.dumps(mapped, ensure_ascii=False, default=str),
        }


# ---- 单例 ----
analyze_service = AnalyzeService(repo=AnalysisRepository())


def _get_expired_cache(offer_id: str) -> dict[str, Any] | None:
    """读取过期缓存（风险 #3 #7：超时/失败时的降级数据源）。"""
    entry = _cache_store.get(offer_id)
    if entry:
        return entry[1]
    return None
