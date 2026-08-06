"""1688 商品分析服务 — 缓存→限流→Apify→判词→display→入库 全流程编排。

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
from adapters.apify_adapter import apify_adapter, get_apify_call_count
from domain import cache as analysis_cache
from domain.display_builder import build_display
from domain.product_mapper import map_raw
from domain.quota import refund as quota_refund
from domain.translator import translate_display
from domain.verdict_engine import judge_all
from repositories.analysis_repo import AnalysisRepository
from utils.exceptions import ExternalServiceError
from utils.logger import get_logger

logger = get_logger(__name__)

# ---- 异步任务管理 ----
_pending: dict[str, asyncio.Task[dict[str, Any]]] = {}  # {offer_id: Task}  请求合并（风险 #2）
_tasks: dict[str, dict[str, Any]] = {}        # {task_id: {status, result, ...}}  异步轮询（风险 #10）
TASK_TTL = Config.TASK_TTL  # 任务结果保留时长（秒）

# ---- 失败重试上限（同一 offer_id 失败 ≥3 次 → 拒绝） ----
_FAIL_TTL: float = 86400.0  # 失败计数 24h 后自动清零
_fail_count: dict[str, tuple[int, float]] = {}  # {offer_id: (count, timestamp)}


def _on_apify_fail(offer_id: str, quota_key: str) -> None:
    """Apify 失败：递增失败计数 + 退还配额。"""
    entry = _fail_count.get(offer_id)
    now = time.time()
    if entry is None or (now - entry[1]) > _FAIL_TTL:
        _fail_count[offer_id] = (1, now)
    else:
        _fail_count[offer_id] = (entry[0] + 1, entry[1])
    if quota_key:
        quota_refund(quota_key)

# ---- display 缓存（key=offer_id:lang，纯内存，30min TTL） ----
_display_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_DISPLAY_CACHE_TTL: int = 43200  # 12 小时
_DISPLAY_CACHE_MAX: int = 500


class AnalyzeService:
    """商品分析编排。依赖注入。"""

    def __init__(self, repo: AnalysisRepository):
        self.repo = repo

    # ------------------------------------------------------------------
    # 公开接口：异步轮询模式（风险 #10）
    # ------------------------------------------------------------------

    async def start(self, offer_id: str, user_id: int = 0, raw_url: str = "", lang: str = "", quota_key: str = "") -> str:
        """启动分析，立即返回 task_id。

        后台执行：缓存检查 → Apify → 判词 → build_display → translate → 入库。
        前端每 2s 轮询 GET /api/analyze/{task_id}。
        quota_key: 配额退款用（路由层传入的 IP 或 user:{id}）。
        """
        # 清理过期 task + 过期失败计数（每次新请求触发，无需后台定时器）
        _now = time.time()
        _expired_tasks = [tid for tid, t in _tasks.items() if _now - t["created_at"] > TASK_TTL]
        for tid in _expired_tasks:
            del _tasks[tid]
        _expired_fails = [oid for oid, v in _fail_count.items() if _now - v[1] > _FAIL_TTL]
        for oid in _expired_fails:
            del _fail_count[oid]

        # 失败次数上限检查：同 offer_id 连续失败 ≥3 次 → 拒绝
        _fail_entry = _fail_count.get(offer_id)
        _fail_total = _fail_entry[0] if _fail_entry else 0
        if _fail_total >= 3:
            logger.warning(f"offer_id={offer_id} 连续失败 3 次，拒绝重试")
            task_id = str(uuid.uuid4())[:8]
            _tasks[task_id] = {
                "status": "failed",
                "error": "该链接连续获取失败，请明天再试或联系 WhatsApp",
                "error_msg_code": "FETCH_FAILED_RETRY_TOMORROW",
                "error_http_status": 503,
                "created_at": time.time(),
            }
            return task_id
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
                    _tasks[task_id] = {"status": "failed", "error": str(e),
                                       "error_msg_code": "INTERNAL_ERROR",
                                       "error_http_status": 500, "created_at": time.time()}

            asyncio.create_task(_wait_existing())
            return task_id

        task_id = str(uuid.uuid4())[:8]
        _tasks[task_id] = {"status": "pending", "result": None, "created_at": time.time()}
        _pending[offer_id] = asyncio.create_task(self._run(task_id, offer_id, raw_url, lang, quota_key))
        return task_id

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """查询任务状态。None = 不存在或已过期。"""
        task = _tasks.get(task_id)
        if task and time.time() - task["created_at"] > TASK_TTL:
            del _tasks[task_id]
            return None
        return task

    def create_done_task(self, result: dict[str, Any]) -> str:
        """缓存命中时创建即时完成的任务，统一 POST 响应契约。"""
        task_id: str = str(uuid.uuid4())[:8]
        _tasks[task_id] = {"status": "done", "result": result, "created_at": time.time()}
        return task_id

    async def get_history(self, user_id: int, limit: int = 20) -> list[dict[str, Any]]:
        """查用户最近的分析记录（只读 DB，不调 Apify）。
        从 display_i18n 提取分析语言 + 卖家标签，供前端显示本地货币价格。
        """
        rows = await self.repo.get_history(user_id, limit)
        for row in rows:
            lang: str = ""
            seller_label: str = ""
            di18n_raw = row.pop("display_i18n", None)
            if di18n_raw:
                try:
                    di18n: dict[str, Any] = json.loads(di18n_raw) if isinstance(di18n_raw, str) else di18n_raw
                    if di18n:
                        lang = next(iter(di18n), "")
                        first_display: dict[str, Any] = di18n.get(lang, {})  # type: ignore[assignment]
                        trust: dict[str, Any] = first_display.get("trustBar", {}) if isinstance(first_display, dict) else {}  # type: ignore[assignment]
                        seller_label = trust.get("label", "")
                except (json.JSONDecodeError, TypeError, StopIteration):
                    pass
            row["lang"] = lang
            row["seller_label"] = seller_label
        return rows

    async def delete_record(self, analysis_id: int, user_id: int) -> bool:
        """删除一条分析记录。校验归属，删除成功返回 True。"""
        return await self.repo.delete(analysis_id, user_id)

    async def get_saved_report(self, offer_id: str, user_id: int, lang: str = "") -> dict[str, Any] | None:
        """从 DB 读已保存的报告。display_i18n 懒加载。

        ① display_i18n.{lang} 存在 → 0 等待，直接返回
        ② display_i18n 为空或无此语言 → build_display → 翻译 → 写入 DB → 返回
        ③ result_json 不存在 → 返回 None
        """
        result = await self.repo.get_by_offer_id(offer_id, user_id)
        if not result:
            return None

        safe_lang: str = lang if lang in ("en", "vi", "th", "id", "zh") else "en"

        # ① 查 display_i18n 缓存
        display_i18n_raw: str | None = await self.repo.get_display_i18n(offer_id, user_id)
        display_i18n: dict[str, Any] = {}
        if display_i18n_raw:
            try:
                display_i18n = json.loads(display_i18n_raw)
            except json.JSONDecodeError:
                display_i18n = {}

        if safe_lang in display_i18n and display_i18n[safe_lang]:
            result["display"] = display_i18n[safe_lang]
            return result

        # ② 构建 + 翻译 + 持久化
        display = build_display(result, safe_lang)
        if safe_lang != "zh":
            try:
                display = await translate_display(display, safe_lang)
            except Exception:
                logger.exception("translate_display failed in get_saved_report, using untranslated display")

        # 仅持久化成功的翻译。翻译失败不缓存（下次请求可重试），zh 无需翻译直接缓存。
        if safe_lang == "zh" or display.get("_translatedLang"):
            display_i18n[safe_lang] = display
            try:
                await self.repo.update_display_i18n(
                    offer_id, user_id,
                    json.dumps(display_i18n, ensure_ascii=False),
                )
            except Exception:
                logger.exception("Failed to persist display_i18n")

        result["display"] = display
        return result

    async def save_report(self, user_id: int, offer_id: str) -> dict[str, Any] | None:
        """用户手动保存分析报告到 DB。

        从内存缓存取 mapped → 扫描 _display_cache 取已翻译 display
        → 检查 20 条上限 → repo.upsert(mapped + display_i18n)。
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

        # 取已翻译的 display（内存缓存中有几语言就写几语言）
        display_i18n: dict[str, Any] = {}
        for lang in ("en", "vi", "th", "id"):
            d = _display_cache_get(offer_id, lang)
            if d is not None:
                display_i18n[lang] = d

        await self._save_to_db_upsert(cached, display_i18n, user_id, offer_id)
        return cached

    # ------------------------------------------------------------------
    # 后台分析流水线
    # ------------------------------------------------------------------

    async def _run(self, task_id: str, offer_id: str, raw_url: str, lang: str = "", quota_key: str = "") -> dict[str, Any]:
        """完整分析流水线（在后台 asyncio.Task 中执行）。"""
        t0 = time.time()
        apify_count_before = get_apify_call_count()
        try:
            _tasks[task_id]["status"] = "running"

            # ---- 1. 缓存检查（风险 #1） ----
            cached = analysis_cache.get(offer_id)
            if cached:
                t1 = time.time()
                logger.info(f"[流水线] offer_id={offer_id} 缓存命中 | 跳过Apify | 耗时={t1 - t0:.2f}s")
                result = await build_result_with_display(cached, offer_id, lang)
                t2 = time.time()
                display = result.get("display", {})
                display_size = len(str(display))
                logger.info(
                    f"[流水线] ✓ 完成(缓存) offer_id={offer_id} task_id={task_id} "
                    f"总耗时={t2 - t0:.2f}s displaySize={display_size}B "
                    f"Apify调用=0(缓存) Qwen={'✓' if display.get('_translatedLang') else '⊘'}"
                )
                _tasks[task_id] = {"status": "done", "result": result, "created_at": time.time()}
                return result

            # ---- 2. Apify 抓取（风险 #3：90s 超时） ----
            try:
                raw = await apify_adapter.fetch_product_by_url(raw_url or Config.URL_1688_DETAIL.format(offer_id=offer_id))
            except ExternalServiceError as e:
                logger.error(f"Apify fetch failed: {e}")
                is_quota = e.details.get("reason") == "quota_exhausted" if e.details else False
                # 过期缓存兜底（风险 #3 + #7 一级降级）
                expired = _get_expired_cache(offer_id)
                if expired:
                    result = await build_result_with_display(expired, offer_id, lang)
                    _tasks[task_id] = {
                        "status": "done", "result": result,
                        "warning": "数据可能不是最新，今日分析额度已用完" if is_quota else "数据可能不是最新，该链接当前无法获取",
                        "warning_msg_code": "STALE_DATA_QUOTA_EXHAUSTED" if is_quota else "STALE_DATA_FETCH_FAILED",
                        "created_at": time.time(),
                    }
                    return result
                # 无缓存 → 区分错误原因
                if is_quota:
                    _tasks[task_id] = {"status": "failed", "error": "今日分析服务额度已用完，请明天再试",
                                       "error_msg_code": "APIFY_QUOTA_EXHAUSTED",
                                       "error_http_status": 403, "created_at": time.time()}
                else:
                    _tasks[task_id] = {"status": "failed", "error": "获取失败，请稍后重试。如持续失败请联系客服",
                                       "error_msg_code": "FETCH_FAILED_RETRY_LATER",
                                       "error_http_status": 502, "created_at": time.time()}
                _on_apify_fail(offer_id, quota_key)
                raise
            except Exception as e:
                logger.error(f"Apify fetch failed: {e}")
                # 过期缓存兜底（风险 #3 + #7 一级降级）
                expired = _get_expired_cache(offer_id)
                if expired:
                    result = await build_result_with_display(expired, offer_id, lang)
                    _tasks[task_id] = {
                        "status": "done", "result": result,
                        "warning": "数据可能不是最新，该链接当前无法获取",
                        "warning_msg_code": "STALE_DATA_FETCH_FAILED",
                        "created_at": time.time(),
                    }
                    return result
                # 无缓存（风险 #7 三级降级）
                _tasks[task_id] = {"status": "failed", "error": "获取失败，请稍后重试。如持续失败请联系客服",
                                   "error_msg_code": "FETCH_FAILED_RETRY_LATER",
                                   "error_http_status": 502, "created_at": time.time()}
                _on_apify_fail(offer_id, quota_key)
                raise ExternalServiceError(service_name="Apify", details={"reason": "fetch_failed"}) from e

            if raw is None:
                expired = _get_expired_cache(offer_id)
                if expired:
                    result = await build_result_with_display(expired, offer_id, lang)
                    _tasks[task_id] = {
                        "status": "done", "result": result,
                        "warning": "数据可能不是最新，该链接当前无法获取",
                        "warning_msg_code": "STALE_DATA_FETCH_FAILED",
                        "created_at": time.time(),
                    }
                    return result
                _tasks[task_id] = {
                    "status": "failed",
                    "error": "该链接可能已下架，请检查后重试",
                    "error_msg_code": "PRODUCT_NOT_FOUND",
                    "error_http_status": 404,
                    "created_at": time.time(),
                }
                _on_apify_fail(offer_id, quota_key)
                raise ExternalServiceError(service_name="Apify", details={"reason": "empty_result"})

            # ---- 3. 映射 + 判词 ----
            t_apify = time.time()
            logger.info(f"[流水线] offer_id={offer_id} Apify完成 耗时={t_apify - t0:.1f}s | 开始映射+判词")

            mapped = map_raw(raw, raw_url, offer_id)

            # 判词（风险 #4 #5 #6）
            verdicts = judge_all(mapped)
            mapped["verdict_product"] = verdicts["product"]
            mapped["verdict_factory"] = verdicts["factory"]
            mapped["verdict_sample"] = verdicts["sample"]

            t_mapped = time.time()
            logger.info(
                f"[流水线] offer_id={offer_id} 映射+判词完成 耗时={t_mapped - t_apify:.1f}s "
                f"判词product={verdicts['product'].get('key', '?')} "
                f"factory={verdicts['factory'].get('key', '?')}"
            )
            logger.info(f"[TRACE-MAPPED] offer_id={offer_id} lang={lang} mapped={json.dumps(mapped, ensure_ascii=False, default=str)}")

            # ---- 4. 写缓存（风险 #1 #14 L2） ----
            analysis_cache.set(offer_id, mapped)
            _fail_count.pop(offer_id, None)  # 成功后清除失败计数

            # ---- 5. build_display + translate（新增：并行运行策略） ----
            result = await build_result_with_display(mapped, offer_id, lang)

            t_end = time.time()
            _tasks[task_id] = {"status": "done", "result": result, "created_at": t_end}
            qwen_called = bool(lang) and lang != "zh"
            display: dict[str, Any] = result.get("display", {}) or {}
            display_lang: str = str(display.get("_translatedLang", ""))
            qwen_ok = bool(display_lang)
            apify_count_after = get_apify_call_count()
            apify_delta = apify_count_after - apify_count_before
            display_size = len(str(display))
            logger.info(
                f"[流水线] ✓ 完成 offer_id={offer_id} task_id={task_id} "
                f"总耗时={t_end - t0:.1f}s "
                f"Apify={t_mapped - t0:.1f}s(调用{apify_delta}次) "
                f"判词+mapper={t_end - t_mapped:.1f}s "
                f"Qwen={'✓' + display_lang if qwen_ok else ('⚠降级' if qwen_called else '⊘跳过')} "
                f"displaySize={display_size}B"
            )
            return result

        except ExternalServiceError:
            raise
        except Exception as e:
            logger.exception(f"Analysis failed: offer_id={offer_id}")
            _tasks[task_id] = {"status": "failed", "error": "服务器内部错误，请稍后重试",
                               "error_msg_code": "INTERNAL_ERROR",
                               "error_http_status": 500, "created_at": time.time()}
            raise ExternalServiceError(service_name="分析引擎") from e
        finally:
            _pending.pop(offer_id, None)

    async def _save_to_db_upsert(self, mapped: dict[str, Any], display_i18n: dict[str, Any], user_id: int, offer_id: str) -> None:
        """同步写入 analysis 表（用户手动保存，跑 upsert 不报重复键错误）。"""
        await self.repo.upsert(self._db_data(mapped, display_i18n, user_id, offer_id))

    def _db_data(self, mapped: dict[str, Any], display_i18n: dict[str, Any], user_id: int, offer_id: str) -> dict[str, Any]:
        """提取 DB 写入字段。列字段仅供历史列表快速展示，完整数据在 result_json 和 display_i18n。"""
        # 取翻译后的标题（优先 display_i18n 第一个语言，降级中文原文）
        title: str | None = mapped.get("title")
        if display_i18n:
            first_display: dict[str, Any] = next(iter(display_i18n.values()))
            if first_display.get("title"):
                title = first_display["title"]
        data: dict[str, Any] = {
            "user_id": user_id,
            "offer_id": offer_id,
            "status": "done",
            "title": title,
            "image_url": mapped.get("image"),
            "price_min": mapped.get("priceCNY", {}).get("low") if mapped.get("priceCNY") else None,  # type: ignore[reportUnknownMemberType]
            "price_max": mapped.get("priceCNY", {}).get("high") if mapped.get("priceCNY") else None,  # type: ignore[reportUnknownMemberType]
            "apify_task_id": mapped.get("apify_task_id"),
            "result_json": json.dumps(mapped, ensure_ascii=False, default=str),
        }
        if display_i18n:
            data["display_i18n"] = json.dumps(display_i18n, ensure_ascii=False)
        return data


# ---- 单例 ----
analyze_service = AnalyzeService(repo=AnalysisRepository())


async def build_result_with_display(mapped: dict[str, Any], offer_id: str, lang: str) -> dict[str, Any]:
    """并行运行策略：mapped（V1 底线）+ display（V2 新增）。

    display 始终构建（不含 lang 时用中文原文）。
    build_display 和 translate 各自独立 try/except，崩了不影响 mapped。
    """
    result: dict[str, Any] = {**mapped}

    # 始终构建 display（即使无 lang，也给中文版 display）
    try:
        display = build_display(mapped, lang)
        logger.info(f"[TRACE-DISPLAY-PRE] offer_id={offer_id} lang={lang} display={json.dumps(display, ensure_ascii=False, default=str)}")
    except Exception:
        logger.exception("build_display failed")
        return result

    # 有 lang 时查 display 缓存 + 翻译
    if lang:
        cached_display: dict[str, Any] | None = _display_cache_get(offer_id, lang)
        if cached_display is not None:
            result["display"] = cached_display
            return result

        try:
            display = await translate_display(display, lang)
            logger.info(f"[TRACE-DISPLAY-POST] offer_id={offer_id} lang={lang} display={json.dumps(display, ensure_ascii=False, default=str)}")
        except Exception:
            logger.exception("translate_display failed, using untranslated display")

        _display_cache_set(offer_id, lang, display)

    result["display"] = display
    return result


def _display_cache_get(offer_id: str, lang: str) -> dict[str, Any] | None:
    """读 display 缓存。过期返回 None。"""
    key: str = f"{offer_id}:{lang}"
    entry: tuple[float, dict[str, Any]] | None = _display_cache.get(key)
    if entry is None:
        return None
    ts, data = entry
    if time.time() - ts < _DISPLAY_CACHE_TTL:
        return data
    del _display_cache[key]
    return None


def _display_cache_set(offer_id: str, lang: str, data: dict[str, Any]) -> None:
    """写 display 缓存。超过上限淘汰最旧条目。"""
    key: str = f"{offer_id}:{lang}"
    _display_cache[key] = (time.time(), data)
    if len(_display_cache) > _DISPLAY_CACHE_MAX:
        oldest_key: str = min(_display_cache.keys(), key=lambda k: _display_cache[k][0])  # type: ignore[reportUnknownArgumentType]
        del _display_cache[oldest_key]


def _get_expired_cache(offer_id: str) -> dict[str, Any] | None:
    """读取过期缓存（风险 #3 #7：超时/失败时的降级数据源）。"""
    return analysis_cache.get_expired(offer_id)
