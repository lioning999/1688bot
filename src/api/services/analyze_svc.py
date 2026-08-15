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
from domain.data.mapper import map_raw
from domain.verdict_engine import judge_all
from repositories.analysis_repo import AnalysisRepository
from repositories.user_repo import UserRepository
from services.ai_verdict_svc import build_result_with_display
from utils.exceptions import ExternalServiceError, InsufficientQuotaError
from utils.logger import get_logger

logger = get_logger(__name__)

# ---- 异步任务管理 ----
_pending: dict[str, asyncio.Task[dict[str, Any]]] = {}  # {offer_id: Task}  请求合并（风险 #2）
_tasks: dict[str, dict[str, Any]] = {}        # {task_id: {status, result, ...}}  异步轮询（风险 #10）
TASK_TTL = Config.TASK_TTL  # 任务结果保留时长（秒）
_MAX_TASKS = 200  # 防止无界增长
_MAX_PENDING = 50

# ---- 失败重试上限（同一 offer_id 失败 ≥3 次 → 拒绝） ----
_FAIL_TTL: float = 86400.0  # 失败计数 24h 后自动清零
_fail_count: dict[str, tuple[int, float]] = {}  # {offer_id: (count, timestamp)}
_MAX_FAIL_COUNT = 1000
_user_repo = UserRepository()


def _on_apify_fail(offer_id: str) -> None:
    """Apify 失败：递增失败计数（配额退还由 _run() 内联处理）。"""
    entry = _fail_count.get(offer_id)
    now = time.time()
    if entry is None or (now - entry[1]) > _FAIL_TTL:
        _fail_count[offer_id] = (1, now)
    else:
        _fail_count[offer_id] = (entry[0] + 1, entry[1])

class AnalyzeService:
    """商品分析编排。依赖注入。"""

    def __init__(self, repo: AnalysisRepository):
        self.repo = repo

    # ------------------------------------------------------------------
    # 公开接口：异步轮询模式（风险 #10）
    # ------------------------------------------------------------------

    async def start(self, offer_id: str, user_id: int = 0, raw_url: str = "",
                    lang: str = "") -> str:
        """启动分析，立即返回 task_id。

        后台执行：DB检查 → Apify → 判词 → build_display → translate → 入库。
        前端每 2s 轮询 GET /api/analyze/{task_id}。
        配额扣减在本方法内完成（decrement_quota）。
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
            task_id = str(uuid.uuid4())
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
            task_id = str(uuid.uuid4())
            _tasks[task_id] = {"status": "pending", "result": None, "created_at": time.time()}

            async def _wait_existing():
                try:
                    result = await existing_task
                    _tasks[task_id] = {"status": "done", "result": result, "created_at": time.time()}
                except Exception:
                    # 透传原始错误码，不让合并请求看到泛化500
                    # 从 existing_task 对应的 _tasks 条目取错误详情
                    err_info = None
                    for _tid, _t in _tasks.items():
                        if _t.get("status") == "failed" and _t.get("created_at", 0) >= time.time() - 300:
                            err_info = _t
                            break
                    if err_info:
                        _tasks[task_id] = {
                            "status": "failed",
                            "error": err_info.get("error", "请求失败"),
                            "error_msg_code": err_info.get("error_msg_code", "INTERNAL_ERROR"),
                            "error_http_status": err_info.get("error_http_status", 500),
                            "created_at": time.time(),
                        }
                    else:
                        _tasks[task_id] = {"status": "failed", "error": "请求失败",
                                           "error_msg_code": "INTERNAL_ERROR",
                                           "error_http_status": 500, "created_at": time.time()}

            asyncio.create_task(_wait_existing())
            return task_id

        # 先占位（扣配额的 await 之前），阻断并发同 offer_id 重复进入（G1 竞态）
        task_id = str(uuid.uuid4())
        _tasks[task_id] = {"status": "pending", "result": None, "created_at": time.time()}
        task = asyncio.create_task(self._run(task_id, offer_id, raw_url, lang, user_id))
        _pending[offer_id] = task

        # 配额扣减（占位之后，同 offer_id 不重复扣）
        if user_id:
            ok = await _user_repo.decrement_quota(user_id)
            if not ok:
                logger.warning(f"配额扣减失败 user_id={user_id} offer_id={offer_id}")
                # 扣失败：撤占位 + 取消任务，防止无配额仍落库
                _pending.pop(offer_id, None)
                task.cancel()
                _tasks[task_id] = {
                    "status": "failed",
                    "error": "今日分析次数不足，请明天再试",
                    "error_msg_code": "QUOTA_EXHAUSTED",
                    "error_http_status": 403,
                    "created_at": time.time(),
                }
                raise InsufficientQuotaError(
                    resource_type="今日分析次数",
                    msg_code="QUOTA_EXHAUSTED",
                )

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

    async def toggle_favorite(self, analysis_id: int, user_id: int) -> bool | None:
        """切换收藏状态。返回切换后的状态 True=已收藏/False=未收藏，记录不存在返回 None。"""
        return await self.repo.toggle_favorite(analysis_id, user_id)

    async def get_saved_report(self, offer_id: str, user_id: int, lang: str = "") -> dict[str, Any] | None:
        """从 DB 读已保存的报告，返回缓存好的 display（display_i18n）。

        请求语言有缓存 → 直接返回；没有 → 降级到第一个可用语言。不重跑 mapper/翻译。
        """
        saved = await self.repo.get_by_offer_id(offer_id, user_id)
        if not saved:
            return None

        safe_lang: str = lang if lang in ("en", "vi", "th", "zh") else "en"

        display_i18n_raw = saved.get("display_i18n")
        display_i18n: dict[str, Any] = {}
        if display_i18n_raw:
            try:
                display_i18n = json.loads(display_i18n_raw) if isinstance(display_i18n_raw, str) else display_i18n_raw
            except json.JSONDecodeError:
                display_i18n = {}

        display: dict[str, Any] = display_i18n.get(safe_lang) or next(iter(display_i18n.values()), {})
        return {"display": display}

    async def save_report(self, user_id: int, offer_id: str) -> dict[str, Any] | None:
        """用户手动保存分析报告。

        自动落库已覆盖保存动作，这里退化为从 DB 读回校验：存在返回 raw，不存在返回 None。
        """
        saved = await self.repo.get_by_offer_id(offer_id, user_id)
        if saved is None:
            return None
        return saved.get("raw")

    # ------------------------------------------------------------------
    # 后台分析流水线
    # ------------------------------------------------------------------

    async def _run(self, task_id: str, offer_id: str, raw_url: str, lang: str = "", user_id: int = 0) -> dict[str, Any]:
        """完整分析流水线（在后台 asyncio.Task 中执行）。"""
        t0 = time.time()
        apify_count_before = get_apify_call_count()
        try:
            _tasks[task_id]["status"] = "running"

            # ---- 1. DB 检查（3.1：复用 raw_json + display_i18n） ----
            saved = await self.repo.get_by_offer_id(offer_id, user_id)
            if saved:
                safe_lang = lang if lang in ("en", "vi", "th", "zh") else "zh"
                display_i18n: dict[str, Any] = {}
                di18n_raw = saved.get("display_i18n")
                if di18n_raw:
                    try:
                        display_i18n = json.loads(di18n_raw) if isinstance(di18n_raw, str) else di18n_raw
                    except json.JSONDecodeError:
                        display_i18n = {}

                # ② 有当前语言 → 直接返回（跳过 Apify + mapper + judge）
                if safe_lang in display_i18n and display_i18n[safe_lang]:
                    result = {"display": display_i18n[safe_lang]}
                    _tasks[task_id] = {"status": "done", "result": result, "created_at": time.time()}
                    await _user_repo.increment_quota(user_id)
                    logger.info(f"[流水线] offer_id={offer_id} DB命中语言{safe_lang} | 跳过Apify | 退配额 | 耗时={time.time() - t0:.2f}s")
                    return result

                # ③ 有 raw_json 无当前语言 → 重建（跳过 Apify）
                mapped = map_raw(saved.get("raw", {}), raw_url, offer_id)
                verdicts = judge_all(mapped)
                mapped["verdict_product"] = verdicts["product"]
                mapped["verdict_factory"] = verdicts["factory"]
                mapped["verdict_sample"] = verdicts["sample"]
                result = await build_result_with_display(mapped, offer_id, safe_lang)
                display = result.get("display", {}) or {}
                # G12：读 _aiGenerated（旧名 _translatedLang 恒空导致非 zh 不落库），读后剥离内部标记
                ai_generated = display.pop("_aiGenerated", None)
                if safe_lang == "zh" or ai_generated:
                    display_i18n[safe_lang] = display
                    try:
                        await self.repo.update_display_i18n(offer_id, user_id, json.dumps(display_i18n, ensure_ascii=False))
                    except Exception:
                        logger.exception(f"DB命中重建后追加语言{safe_lang}失败 offer_id={offer_id}")
                _tasks[task_id] = {"status": "done", "result": result, "created_at": time.time()}
                await _user_repo.increment_quota(user_id)
                logger.info(f"[流水线] offer_id={offer_id} DB命中重建语言{safe_lang} | 跳过Apify | 退配额 | 耗时={time.time() - t0:.2f}s")
                return result

            # ---- 2. Apify 抓取（风险 #3：90s 超时） ----
            try:
                raw = await apify_adapter.fetch_product_by_url(raw_url or Config.URL_1688_DETAIL.format(offer_id=offer_id))
            except ExternalServiceError as e:
                logger.error(f"Apify fetch failed: {e}")
                is_quota = e.details.get("reason") == "quota_exhausted" if e.details else False
                # 无缓存 → 区分错误原因
                if is_quota:
                    _tasks[task_id] = {"status": "failed", "error": "今日分析服务额度已用完，请明天再试",
                                       "error_msg_code": "APIFY_QUOTA_EXHAUSTED",
                                       "error_http_status": 403, "created_at": time.time()}
                else:
                    _tasks[task_id] = {"status": "failed", "error": "获取失败，请稍后重试。如持续失败请联系客服",
                                       "error_msg_code": "FETCH_FAILED_RETRY_LATER",
                                       "error_http_status": 502, "created_at": time.time()}
                await _user_repo.increment_quota(user_id)
                _on_apify_fail(offer_id)
                raise
            except Exception as e:
                logger.error(f"Apify fetch failed: {e}")
                # 无缓存（风险 #7 三级降级）
                _tasks[task_id] = {"status": "failed", "error": "获取失败，请稍后重试。如持续失败请联系客服",
                                   "error_msg_code": "FETCH_FAILED_RETRY_LATER",
                                   "error_http_status": 502, "created_at": time.time()}
                await _user_repo.increment_quota(user_id)
                _on_apify_fail(offer_id)
                raise ExternalServiceError(service_name="Apify", details={"reason": "fetch_failed"}) from e

            if raw is None:
                _tasks[task_id] = {
                    "status": "failed",
                    "error": "该链接可能已下架，请检查后重试",
                    "error_msg_code": "PRODUCT_NOT_FOUND",
                    "error_http_status": 404,
                    "created_at": time.time(),
                }
                await _user_repo.increment_quota(user_id)
                _on_apify_fail(offer_id)
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

            _fail_count.pop(offer_id, None)  # 成功后清除失败计数

            # ---- 4. build_display + translate ----
            result = await build_result_with_display(mapped, offer_id, lang)

            # ---- 5. 自动落库（3.6）+ 超限清理（3.7） ----
            display: dict[str, Any] = result.get("display", {}) or {}
            # G12：读 _aiGenerated（旧名 _translatedLang 恒空导致非 zh 不落库），读后剥离内部标记
            display_lang: str = str(display.pop("_aiGenerated", ""))
            save_lang = lang if lang in ("en", "vi", "th", "zh") else "zh"
            if user_id and (save_lang == "zh" or display_lang):
                try:
                    await self._save_to_db_upsert(raw, mapped, {save_lang: display}, user_id, offer_id)
                except Exception:
                    logger.exception(f"自动落库失败 offer_id={offer_id}")
                else:
                    # 3.7 超限清理：FIFO 删最早未收藏
                    try:
                        user_info = await _user_repo.get_quota_info(user_id)
                        tier = str(user_info.get("tier", "free")) if user_info else "free"
                        max_count = Config.HISTORY_PAID_MAX if tier == "paid" else Config.HISTORY_FREE_MAX
                        await self.repo.cleanup_excess(user_id, max_count)
                    except Exception:
                        logger.exception(f"超限清理失败 user_id={user_id}")

            t_end = time.time()
            _tasks[task_id] = {"status": "done", "result": result, "created_at": t_end}
            qwen_called = bool(lang) and lang != "zh"
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
            # 退配额（G4）：mapper/judge/build_display 抛异常时，start 已扣的配额需退还
            await _user_repo.increment_quota(user_id)
            _tasks[task_id] = {"status": "failed", "error": "服务器内部错误，请稍后重试",
                               "error_msg_code": "INTERNAL_ERROR",
                               "error_http_status": 500, "created_at": time.time()}
            raise ExternalServiceError(service_name="分析引擎") from e
        finally:
            _pending.pop(offer_id, None)

    async def _save_to_db_upsert(self, raw: dict[str, Any], mapped: dict[str, Any], display_i18n: dict[str, Any], user_id: int, offer_id: str) -> None:
        """同步写入 analysis 表（raw_json + display_i18n，跑 upsert 不报重复键错误）。"""
        await self.repo.upsert(self._db_data(raw, mapped, display_i18n, user_id, offer_id))

    def _db_data(self, raw: dict[str, Any], mapped: dict[str, Any], display_i18n: dict[str, Any], user_id: int, offer_id: str) -> dict[str, Any]:
        """提取 DB 写入字段。raw_json 存 Apify 原始（唯一数据源），display_i18n 存翻译结果。"""
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
            "raw_json": json.dumps(raw, ensure_ascii=False, default=str),
        }
        if display_i18n:
            data["display_i18n"] = json.dumps(display_i18n, ensure_ascii=False)
        return data


# ---- 单例 ----
analyze_service = AnalyzeService(repo=AnalysisRepository())
