"""AI 判词编排服务 — 评估→打包→Qwen→校验→合并 全流程。

从 analyze_svc.py 拆分（Phase 2 重构）。包含：
  - AI 判词输入打包 + Qwen 调用 + 输出校验 + 逐字段合并
  - build_result_with_display（lang≠zh → AI 路径，lang=zh → 模板路径）
  - display 内存缓存（12h TTL，LRU 淘汰）
"""

import json
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from config import Config
from adapters.qwen_adapter import qwen_adapter
from domain.display.builder import build_display
from domain.display.ai_verdict import pack_ai_input, validate_ai_output
from domain.evaluate import evaluate_product, evaluate_supplier, evaluate_summary
from utils.logger import get_logger

logger = get_logger(__name__)

# ---- AI 判词 prompt 配置 ----
_HERE = Path(__file__).parent.parent / "domain" / "display"
with open(_HERE / "verdict_prompts.json", "r", encoding="utf-8") as _f:
    _VP_AI = json.load(_f)

# ---- display 缓存（key=offer_id:lang，纯内存，12h TTL，O(1) LRU 淘汰） ----
_display_cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
_DISPLAY_CACHE_TTL: int = 43200  # 12 小时
_DISPLAY_CACHE_MAX: int = 500


def get_display_cache(offer_id: str, lang: str) -> dict[str, Any] | None:
    """读 display 缓存。过期返回 None。命中刷新 LRU 顺序。"""
    key: str = f"{offer_id}:{lang}"
    entry: tuple[float, dict[str, Any]] | None = _display_cache.get(key)
    if entry is None:
        return None
    ts, data = entry
    if time.time() - ts < _DISPLAY_CACHE_TTL:
        _display_cache.move_to_end(key)  # LRU: 访问移到末尾
        return data
    del _display_cache[key]
    return None


def set_display_cache(offer_id: str, lang: str, data: dict[str, Any]) -> None:
    """写 display 缓存。O(1) 淘汰最旧条目。"""
    key: str = f"{offer_id}:{lang}"
    _display_cache[key] = (time.time(), data)
    _display_cache.move_to_end(key)
    while len(_display_cache) > _DISPLAY_CACHE_MAX:
        _display_cache.popitem(last=False)  # O(1) 弹出最旧


# ====================================================================
# AI 判词编排
# ====================================================================


async def build_result_with_display(mapped: dict[str, Any], offer_id: str, lang: str) -> dict[str, Any]:
    """构建 display + 翻译（或 AI 判词）。

    lang=zh 或空 → 模板路径（build_display 直接出中文 display）
    lang=en/vi/th → AI 判词路径（build_with_ai：一次 Qwen 出判词+翻译）
    display 构建失败不影响 mapped 返回。
    """
    result: dict[str, Any] = {**mapped}

    try:
        if lang and lang != "zh":
            # AI 判词路径（en/vi/th）
            cached_display: dict[str, Any] | None = get_display_cache(offer_id, lang)
            if cached_display is not None:
                result["display"] = cached_display
                return result

            display = await build_with_ai(mapped, lang)
            logger.info(f"[TRACE-DISPLAY-AI] offer_id={offer_id} lang={lang} "
                        f"aiGenerated={display.get('_aiGenerated', '')} "
                        f"display={json.dumps(display, ensure_ascii=False, default=str)}")
            # 剥离内部标记，不泄漏到前端
            display.pop("_aiGenerated", None)
            set_display_cache(offer_id, lang, display)
        else:
            # 模板路径（zh / 空 lang）
            display = build_display(mapped, lang)
            logger.info(f"[TRACE-DISPLAY-PRE] offer_id={offer_id} lang={lang} "
                        f"display={json.dumps(display, ensure_ascii=False, default=str)}")
    except Exception:
        logger.exception("build_display failed")
        return result

    result["display"] = display
    return result


async def build_with_ai(mapped: dict[str, Any], lang: str) -> dict[str, Any]:
    """AI 判词路径：评估 → 打包 → Qwen → 校验 → 逐字段合并。

    异常/超时/JSON 解析失败/校验失败均降级为模板 display。
    中文用户不走此路径（lang="zh" 直接 build_display 模板兜底）。
    """
    # 1. 构建模板 display（始终作为兜底）
    display: dict[str, Any] = build_display(mapped, lang)

    # 2. 语言检查：仅 en/vi/th 走 AI 判词
    if lang not in ("en", "vi", "th"):
        return display

    if not Config.QWEN_API_KEY:
        logger.warning("[AI判词] 跳过: QWEN_API_KEY 未配置")
        return display

    # 3. 评估（build_display 内部也调了，纯函数重复调用无害）
    try:
        product_raw: dict[str, Any] = evaluate_product(mapped)
        supplier_raw: dict[str, Any] = evaluate_supplier(mapped)
        summary_raw: dict[str, Any] = evaluate_summary(product_raw, supplier_raw)
    except Exception:
        logger.exception("[AI判词] 评估失败，降级模板")
        return display

    # 4. 打包 AI 输入
    try:
        ai_input: dict[str, Any] = pack_ai_input(
            product_raw, supplier_raw, summary_raw, mapped, lang,
        )
    except Exception:
        logger.exception("[AI判词] pack_ai_input 失败，降级模板")
        return display

    # 5. 构建 system prompt
    lang_names: dict[str, str] = {"en": "English", "vi": "Vietnamese", "th": "Thai"}
    lang_name: str = lang_names.get(lang, "English")
    market_note: str = str(_VP_AI.get("market_notes", {}).get(lang, ""))
    system_prompt: str = _VP_AI["system"].replace("{lang_name}", lang_name).replace(
        "{market_note}", market_note,
    )

    # 6. 调 Qwen（8s 超时）
    t0: float = time.time()
    try:
        body: dict[str, Any] | None = await qwen_adapter.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(ai_input, ensure_ascii=False)},
            ],
            timeout=Config.QWEN_TIMEOUT,
        )
    except Exception:
        logger.exception("[AI判词] Qwen 调用异常，降级模板")
        return display

    if body is None:
        logger.warning(f"[AI判词] Qwen 返回 None lang={lang} 耗时={time.time() - t0:.1f}s")
        return display

    content: str = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        logger.warning(f"[AI判词] Qwen 返回空 content lang={lang}")
        return display

    usage: dict[str, Any] = body.get("usage", {})
    logger.info(
        f"[AI判词] Qwen 调用完成 lang={lang} 耗时={time.time() - t0:.1f}s "
        f"tokens in={usage.get('prompt_tokens','?')} out={usage.get('completion_tokens','?')}"
    )

    # 7. 解析 JSON
    try:
        ai: dict[str, Any] = _parse_ai_json(content)
    except Exception:
        logger.exception("[AI判词] JSON 解析失败，降级模板")
        return display

    if not ai:
        return display

    # 8. 逐字段合并（独立校验，单字段失败不影响其他）
    _merge_ai_verdicts(display, ai, ai_input)

    # 9. 标记 AI 生成（translator 据此跳过翻译）
    display["_aiGenerated"] = lang

    return display


def _parse_ai_json(content: str) -> dict[str, Any]:
    """解析 AI 返回的 JSON，处理 markdown 代码块包裹。"""
    content = content.strip()
    if content.startswith("```"):
        lines: list[str] = content.split("\n")
        if lines[-1].strip() == "```":
            content = "\n".join(lines[1:-1])
        else:
            content = "\n".join(lines[1:])
    return json.loads(content)


def _merge_ai_verdicts(
    display: dict[str, Any],
    ai: dict[str, Any],
    ai_input: dict[str, Any],
) -> None:
    """逐字段独立校验 + 替换。单个字段失败不影响其他字段。

    替换映射：
      productEval.verdict    ← ai.product_verdict    (校验: must_mention)
      supplierEval.verdict   ← ai.supplier_verdict   (校验: supplier_must_mention)
      summaryLine.reason     ← ai.summary_verdict    (校验: 数字 + 禁止表述)
      title                  ← ai.translated_title   (基础检查)
      factory.supplierName   ← ai.translated_supplier_name (基础检查)
    """
    # productEval.verdict — 仅检查 product 维度数字
    pv: str = str(ai.get("product_verdict", ""))
    if pv and pv.strip():
        pv = pv.strip()
        if validate_ai_output(pv, ai_input.get("must_mention", []), ai_input,
                              dimension_sections=("product",)):
            if "productEval" in display:
                display["productEval"]["verdict"] = pv
        else:
            logger.info("[AI判词] product_verdict 校验失败，保留模板")

    # supplierEval.verdict — 仅检查 supplier 维度数字
    sv: str = str(ai.get("supplier_verdict", ""))
    if sv and sv.strip():
        sv = sv.strip()
        if validate_ai_output(sv, ai_input.get("supplier_must_mention", []), ai_input,
                              dimension_sections=("supplier",)):
            if "supplierEval" in display:
                display["supplierEval"]["verdict"] = sv
        else:
            logger.info("[AI判词] supplier_verdict 校验失败，保留模板")

    # summaryLine.reason — 检查所有维度数字（默认 product + supplier）
    sum_v: str = str(ai.get("summary_verdict", ""))
    if sum_v and sum_v.strip():
        sum_v = sum_v.strip()
        if validate_ai_output(sum_v, [], ai_input):
            if "summaryLine" in display:
                display["summaryLine"]["reason"] = sum_v
        else:
            logger.info("[AI判词] summary_verdict 校验失败，保留模板")

    # title（基础检查：非空 + 长度合理）
    title: str = str(ai.get("translated_title", ""))
    if title and title.strip() and len(title.strip()) > 3:
        display["title"] = title.strip()

    # factory.supplierName（基础检查：非空 + 长度合理）
    sname: str = str(ai.get("translated_supplier_name", ""))
    if sname and sname.strip() and len(sname.strip()) > 1:
        if "factory" in display:
            display["factory"]["supplierName"] = sname.strip()
