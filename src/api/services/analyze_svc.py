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
from typing import Any, cast

from config import Config
from adapters.apify_adapter import apify_adapter, get_apify_call_count
from domain.data.mapper import map_raw
from repositories.analysis_repo import AnalysisRepository
from repositories.user_repo import UserRepository
from services.ai_verdict_svc import build_result_with_display
from utils.exceptions import ExternalServiceError, InsufficientQuotaError
from utils.logger import get_logger

logger = get_logger(__name__)

# ---- 异步任务管理 ----
_pending: dict[str, dict[str, Any]] = {}  # {offer_id: {task, lang, raw_url}}  请求合并（风险 #2）
_tasks: dict[str, dict[str, Any]] = {}        # {task_id: {status, result, ...}}  异步轮询（风险 #10）
TASK_TTL = Config.TASK_TTL  # 任务结果保留时长（秒）
_MAX_TASKS = Config.MAX_TASKS  # 防止无界增长
_MAX_PENDING = Config.MAX_PENDING

# ---- 失败重试上限（同一 offer_id 失败 ≥3 次 → 拒绝） ----
_FAIL_TTL: float = Config.FAIL_TTL  # 失败计数 24h 后自动清零
_fail_count: dict[str, tuple[int, float]] = {}  # {offer_id: (count, timestamp)}
_MAX_FAIL_COUNT = Config.MAX_FAIL_COUNT
_user_repo = UserRepository()


def _on_apify_fail(offer_id: str) -> None:
    """Apify 失败：递增失败计数（配额退还由 _run() 内联处理）。"""
    entry = _fail_count.get(offer_id)
    now = time.time()
    if entry is None or (now - entry[1]) > _FAIL_TTL:
        _fail_count[offer_id] = (1, now)
    else:
        _fail_count[offer_id] = (entry[0] + 1, entry[1])


def _cleanup_containers() -> None:
    """清理过期条目 + 强制硬上限（每次新请求触发，无后台定时器）。

    铁律五：全局可变容器必须有上限 + 清理机制。
    TTL 兜底过期清理；_MAX_TASKS/_MAX_FAIL_COUNT 硬上限 FIFO 删最旧，防 TTL 窗口内无界增长（G3）。
    """
    _now: float = time.time()
    for _tid, _t in list(_tasks.items()):
        if _now - _t["created_at"] > TASK_TTL:
            del _tasks[_tid]
    for _oid, _v in list(_fail_count.items()):
        if _now - _v[1] > _FAIL_TTL:
            del _fail_count[_oid]
    if len(_tasks) > _MAX_TASKS:
        for _tid, _ in sorted(_tasks.items(), key=lambda kv: kv[1]["created_at"])[:len(_tasks) - _MAX_TASKS]:
            del _tasks[_tid]
    if len(_fail_count) > _MAX_FAIL_COUNT:
        for _oid, _ in sorted(_fail_count.items(), key=lambda kv: kv[1][1])[:len(_fail_count) - _MAX_FAIL_COUNT]:
            del _fail_count[_oid]


def _swallow_task_exception(t: asyncio.Task[dict[str, Any]]) -> None:
    """取回后台任务异常，吞掉 asyncio「Task exception was never retrieved」噪音。

    _run 失败时永远 raise（合并路径靠 await existing_task 透传错误码），
    单请求路径无人 await → 异常未取回会打噪音。此处仅取回，不改传播语义。
    """
    if not t.cancelled():
        t.exception()


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
        # 清理过期 + 硬上限（每次新请求触发，无需后台定时器）
        _cleanup_containers()

        # 失败次数上限检查：同 offer_id 连续失败 ≥3 次 → 拒绝
        _fail_entry = _fail_count.get(offer_id)
        _fail_total = _fail_entry[0] if _fail_entry else 0
        if _fail_total >= Config.FAIL_RETRY_MAX:
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
        # 并发上限（G3）：活跃合并数超 _MAX_PENDING → 拒绝，防 Apify 过载
        if len(_pending) >= _MAX_PENDING and offer_id not in _pending:
            task_id = str(uuid.uuid4())
            _tasks[task_id] = {"status": "failed", "error": "系统繁忙，请稍后重试",
                               "error_msg_code": "GLOBAL_RATE_LIMIT",
                               "error_http_status": 429, "created_at": time.time()}
            return task_id
        # 请求合并（风险 #2）：同一 offer_id 正在分析中 → 等现有结果
        if offer_id in _pending:
            existing = _pending[offer_id]
            existing_task: asyncio.Task[dict[str, Any]] = existing["task"]
            existing_lang: str = str(existing.get("lang", ""))
            logger.info(f"Request coalesced: offer_id={offer_id} existing_lang={existing_lang} req_lang={lang}")
            task_id = str(uuid.uuid4())
            _tasks[task_id] = {"status": "pending", "result": None, "created_at": time.time()}

            if lang and lang != existing_lang:
                # 语言不同（G2）：等第一个完成后复用 raw_json，用第二个 lang 重建（不 Apify，不扣配额）
                async def _wait_and_rebuild() -> None:
                    try:
                        await existing_task
                    except Exception:
                        _tasks[task_id] = {"status": "failed", "error": "请求失败",
                                           "error_msg_code": "INTERNAL_ERROR",
                                           "error_http_status": 500, "created_at": time.time()}
                        return
                    try:
                        saved = await self.repo.get_by_offer_id(offer_id, user_id)
                        if not saved or not saved.get("raw"):
                            _tasks[task_id] = {"status": "failed", "error": "请求失败",
                                               "error_msg_code": "INTERNAL_ERROR",
                                               "error_http_status": 500, "created_at": time.time()}
                            return
                        safe_lang = lang if lang in ("en", "vi", "th", "zh", "ru") else "en"
                        mapped = map_raw(saved.get("raw", {}), raw_url, offer_id)
                        result = await build_result_with_display(mapped, offer_id, safe_lang)
                        display: dict[str, Any] = cast(dict[str, Any], result.get("display")) or {}
                        ai_generated: Any = display.pop("_aiGenerated", None)
                        display_i18n: dict[str, Any] = {}
                        di18n_raw = saved.get("display_i18n")
                        if di18n_raw:
                            display_i18n = json.loads(di18n_raw) if isinstance(di18n_raw, str) else di18n_raw
                        if safe_lang == "zh" or ai_generated:
                            display_i18n[safe_lang] = display
                            await self.repo.update_display_i18n(offer_id, user_id, json.dumps(display_i18n, ensure_ascii=False))
                        _tasks[task_id] = {"status": "done", "result": result, "created_at": time.time()}
                    except Exception:
                        logger.exception(f"合并请求重建语言失败 offer_id={offer_id}")
                        _tasks[task_id] = {"status": "failed", "error": "请求失败",
                                           "error_msg_code": "INTERNAL_ERROR",
                                           "error_http_status": 500, "created_at": time.time()}

                asyncio.create_task(_wait_and_rebuild())
                return task_id

            async def _wait_existing() -> None:
                try:
                    result = await existing_task
                    _tasks[task_id] = {"status": "done", "result": result, "created_at": time.time()}
                except Exception:
                    # 透传原始错误码，不让合并请求看到泛化500
                    # 从 existing_task 对应的 _tasks 条目取错误详情
                    err_info = None
                    for _tid, _t in _tasks.items():
                        if _t.get("status") == "failed" and _t.get("created_at", 0) >= time.time() - Config.ERROR_LOOKBACK_SECONDS:
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
        task.add_done_callback(_swallow_task_exception)
        _pending[offer_id] = {"task": task, "lang": lang, "raw_url": raw_url}

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

    async def get_history(self, user_id: int, limit: int = 0) -> list[dict[str, Any]]:
        """查用户最近的分析记录（只读 DB，不调 Apify）。
        从 display_i18n 提取分析语言 + 卖家标签，供前端显示本地货币价格。
        limit=0 → 按用户 tier 取上限（free=20/paid=100），否则用给定值。
        """
        if limit <= 0:
            info = await _user_repo.get_quota_info(user_id)
            tier = str(info.get("tier", "free")) if info else "free"
            limit = Config.HISTORY_PAID_MAX if tier == "paid" else Config.HISTORY_FREE_MAX
        rows = await self.repo.get_history(user_id, limit)
        for row in rows:
            lang: str = ""
            seller_label: str = ""
            seller_grade: str = "none"
            di18n_raw = row.pop("display_i18n", None)
            if di18n_raw:
                try:
                    di18n: dict[str, Any] = json.loads(di18n_raw) if isinstance(di18n_raw, str) else di18n_raw
                    if di18n:
                        lang = next(iter(di18n), "")
                        first_display: Any = di18n.get(lang, {})
                        if isinstance(first_display, dict):
                            fd: dict[str, Any] = cast(dict[str, Any], first_display)
                            trust: dict[str, Any] = cast(dict[str, Any], fd.get("trustBar")) or {}
                            seller_label = str(trust.get("label", ""))
                            supplier_eval: dict[str, Any] = cast(dict[str, Any], fd.get("supplierEval")) or {}
                            seller_grade = str(supplier_eval.get("grade", "none"))
                except (json.JSONDecodeError, TypeError, StopIteration):
                    pass
            row["lang"] = lang
            row["seller_label"] = seller_label
            row["seller_grade"] = seller_grade
        return rows

    async def delete_record(self, analysis_id: int, user_id: int) -> bool:
        """删除一条分析记录。校验归属，删除成功返回 True。"""
        return await self.repo.delete(analysis_id, user_id)

    async def toggle_favorite(self, analysis_id: int, user_id: int) -> bool | None:
        """切换收藏状态。返回切换后的状态 True=已收藏/False=未收藏，记录不存在返回 None。"""
        return await self.repo.toggle_favorite(analysis_id, user_id)

    async def get_saved_report(self, offer_id: str, user_id: int, lang: str = "") -> dict[str, Any] | None:
        """从 DB 读已保存的报告，返回缓存好的 display（display_i18n）。

        请求语言有缓存 → 直接返回；没有 → 复用 raw_json 重建该语言（跳过 Apify）。
        """
        saved = await self.repo.get_by_offer_id(offer_id, user_id)
        if not saved:
            return None

        safe_lang: str = lang if lang in ("en", "vi", "th", "zh", "ru") else "en"

        display_i18n_raw = saved.get("display_i18n")
        display_i18n: dict[str, Any] = {}
        if display_i18n_raw:
            try:
                display_i18n = json.loads(display_i18n_raw) if isinstance(display_i18n_raw, str) else display_i18n_raw
            except json.JSONDecodeError:
                display_i18n = {}

        # 有当前语言缓存 → 直接返回；缺语言 → 复用 raw_json 重建（跳过 Apify，跑 mapper + 判词/翻译）
        if safe_lang in display_i18n and display_i18n[safe_lang]:
            return {"display": display_i18n[safe_lang]}

        raw: dict[str, Any] = saved.get("raw", {}) or {}
        raw_url: str = str(raw.get("detailUrl") or "") or Config.URL_1688_DETAIL.format(offer_id=offer_id)
        mapped: dict[str, Any] = map_raw(raw, raw_url, offer_id)
        result: dict[str, Any] = await build_result_with_display(mapped, offer_id, safe_lang)
        display: dict[str, Any] = result.get("display", {}) or {}
        # G12：读 _aiGenerated（旧名 _translatedLang 恒空导致非 zh 不落库），读后剥离内部标记
        ai_generated = display.pop("_aiGenerated", None)
        if safe_lang == "zh" or ai_generated:
            display_i18n[safe_lang] = display
            try:
                await self.repo.update_display_i18n(offer_id, user_id, json.dumps(display_i18n, ensure_ascii=False))
            except Exception:
                logger.exception(f"历史报告重建语言{safe_lang}后回写失败 offer_id={offer_id}")
        return {"display": display}

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
                safe_lang = lang if lang in ("en", "vi", "th", "zh", "ru") else "en"
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
                is_timeout = e.details.get("reason") == "timeout" if e.details else False
                # 无缓存 → 区分错误原因
                if is_quota:
                    _tasks[task_id] = {"status": "failed", "error": "今日分析服务额度已用完，请明天再试",
                                       "error_msg_code": "APIFY_QUOTA_EXHAUSTED",
                                       "error_http_status": 403, "created_at": time.time()}
                elif is_timeout:
                    _tasks[task_id] = {"status": "failed", "error": "获取超时，请稍后重试",
                                       "error_msg_code": "TIMEOUT_RETRY",
                                       "error_http_status": 504, "created_at": time.time()}
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
                # 空结果 ≠ 已下架：商品可能存在，是 Apify actor 抓取失败 → 退配额 + 中性文案防误导
                _tasks[task_id] = {
                    "status": "failed",
                    "error": "数据获取失败，已退还本次分析次数，请稍后重试",
                    "error_msg_code": "FETCH_EMPTY_QUOTA_SAVED",
                    "error_http_status": 502,
                    "created_at": time.time(),
                }
                await _user_repo.increment_quota(user_id)
                _on_apify_fail(offer_id)
                raise ExternalServiceError(service_name="Apify", details={"reason": "empty_result"})

            # ---- 3. 映射 + 判词 ----
            t_apify = time.time()
            logger.info(f"[流水线] offer_id={offer_id} Apify完成 耗时={t_apify - t0:.1f}s | 开始映射+判词")

            mapped = map_raw(raw, raw_url, offer_id)

            t_mapped = time.time()
            logger.info(f"[流水线] offer_id={offer_id} 映射完成 耗时={t_mapped - t_apify:.1f}s")
            logger.info(f"[TRACE-MAPPED] offer_id={offer_id} lang={lang} mapped={json.dumps(mapped, ensure_ascii=False, default=str)}")

            _fail_count.pop(offer_id, None)  # 成功后清除失败计数

            # ---- 4. build_display + translate ----
            result = await build_result_with_display(mapped, offer_id, lang)

            # ---- 5. 自动落库（3.6）+ 超限清理（3.7） ----
            display: dict[str, Any] = result.get("display", {}) or {}
            # G12：读 _aiGenerated（旧名 _translatedLang 恒空导致非 zh 不落库），读后剥离内部标记
            display_lang: str = str(display.pop("_aiGenerated", ""))
            save_lang = lang if lang in ("en", "vi", "th", "zh", "ru") else "en"
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
