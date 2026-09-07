"""AI 判词编排服务 — 评估→打包→Qwen→校验→合并 全流程。

从 analyze_svc.py 拆分（Phase 2 重构）。包含：
  - AI 判词输入打包 + Qwen 调用 + 输出校验 + 逐字段合并
  - build_result_with_display（lang ∈ AI_LANGS → AI 路径，zh/其他 → 模板路径）
"""

import json
import re
import time
from pathlib import Path
from typing import Any

from config import Config
from adapters.qwen_adapter import qwen_adapter
from domain.display.builder import build_display
from domain.display.ai_verdict import pack_ai_input, validate_ai_output
from domain.evaluate import evaluate_product, evaluate_supplier, evaluate_summary
from utils.i18n_core import AI_LANGS
from utils.logger import get_logger

logger = get_logger(__name__)

_CJK_RE = re.compile(r"[一-鿿]")


def _strip_cjk(text: str) -> str:
    """去残留汉字（AI 未完全转写时保拉丁段）；若纯中文则原样返回（病理态，避免丢字段）。"""
    out = _CJK_RE.sub("", text)
    return out if out.strip() else text

# ---- AI 判词 prompt 配置 ----
_HERE = Path(__file__).parent.parent / "domain" / "display"
with open(_HERE / "verdict_prompts.json", "r", encoding="utf-8") as _f:
    _VP_AI = json.load(_f)

# ====================================================================
# AI 判词编排
# ====================================================================


async def build_result_with_display(mapped: dict[str, Any], offer_id: str, lang: str) -> dict[str, Any]:
    """构建 display + 翻译（或 AI 判词）。

    lang=zh 或空 → 模板路径（build_display 直接出中文 display）
    lang ∈ AI_LANGS（en/vi/th/ru）→ AI 判词路径（build_with_ai：一次 Qwen 出判词+翻译）
    display 构建失败不影响 mapped 返回。
    """
    result: dict[str, Any] = {**mapped}

    try:
        money: dict[str, Any] | None = _make_money(lang)
        if lang in AI_LANGS:
            # AI 判词路径（en/vi/th/ru）
            display = await build_with_ai(mapped, lang, money)
            logger.info(f"[TRACE-DISPLAY-AI] offer_id={offer_id} lang={lang} "
                        f"aiGenerated={display.get('_aiGenerated', '')} "
                        f"display={json.dumps(display, ensure_ascii=False, default=str)}")
        else:
            # 模板路径（zh / 空 lang）
            display = build_display(mapped, lang, money)
            logger.info(f"[TRACE-DISPLAY-PRE] offer_id={offer_id} lang={lang} "
                        f"display={json.dumps(display, ensure_ascii=False, default=str)}")
    except Exception:
        logger.exception("build_display failed")
        return result

    result["display"] = display
    return result


def _make_money(lang: str) -> dict[str, Any] | None:
    """按目标语言返回本地货币配置（符号 / 1 CNY 兑换系数 / 小数位 / 美元系数）。

    zh（及空 lang）也返回 dict（per_cny=1.0 保持人民币），用于携带 usd_per_cny 供拿样美元价。
    """
    cny_usd: float = float(Config.CNY_USD_RATE)
    usd_per_cny: float = 1.0 / cny_usd  # USD 价系数：display.price.usd = CNY × usd_per_cny
    if lang == "en":
        return {"symbol": "$", "per_cny": usd_per_cny, "decimals": 2, "usd_per_cny": usd_per_cny}
    if lang == "vi":
        return {"symbol": "₫", "per_cny": float(Config.FX_VND) / cny_usd, "decimals": 0, "usd_per_cny": usd_per_cny}
    if lang == "th":
        return {"symbol": "฿", "per_cny": float(Config.FX_THB) / cny_usd, "decimals": 0, "usd_per_cny": usd_per_cny}
    if lang == "ru":
        return {"symbol": "₽", "per_cny": float(Config.FX_RUB) / cny_usd, "decimals": 0, "usd_per_cny": usd_per_cny}
    return {"symbol": "¥", "per_cny": 1.0, "decimals": 2, "usd_per_cny": usd_per_cny}


async def build_with_ai(mapped: dict[str, Any], lang: str, money: dict[str, Any] | None = None) -> dict[str, Any]:
    """AI 判词路径：评估 → 打包 → Qwen → 校验 → 逐字段合并。

    异常/超时/JSON 解析失败/校验失败均降级为模板 display。
    中文用户不走此路径（lang="zh" 直接 build_display 模板兜底）。
    """
    # 1. 构建模板 display（始终作为兜底）
    display: dict[str, Any] = build_display(mapped, lang, money)

    # 2. 语言检查：仅 en/vi/th/ru 走 AI 判词
    if lang not in AI_LANGS:
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
            money=money,
        )
    except Exception:
        logger.exception("[AI判词] pack_ai_input 失败，降级模板")
        return display

    # 5. 构建 system prompt（每种语言独立的母语 prompt，杜绝翻译腔）
    prompt_config: dict[str, Any] = _VP_AI.get(lang, _VP_AI.get("en", {}))
    system_prompt: str = prompt_config.get("system", "")
    if not system_prompt:
        logger.warning(f"[AI判词] 语言 {lang} 无 system prompt，降级模板")
        return display

    # 6. 调 Qwen（超时 Config.QWEN_TIMEOUT）
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

    # 8. 逐字段合并（title + supplierName + 判词，逐字段校验）
    failures: list[dict[str, Any]] = _merge_ai_verdicts(display, ai, ai_input)["failures"]

    # 8.5 校验不过 → 带错误反馈重写（重写仅 1 次，总调用 ≤2 次；仍不对即降级模板，
    # 防多烧 token。每轮把上一版失败字段清单作反馈，通过的字段已即时合入 display）
    retries = 0
    while failures and retries < 1:
        retries += 1
        logger.info(f"[AI判词] {len(failures)} 个字段校验失败，第 {retries} 次带反馈重写: "
                    + ", ".join(f["field"] for f in failures))
        retry_user: str = _build_retry_feedback(failures)
        t_retry: float = time.time()
        try:
            body_r: dict[str, Any] | None = await qwen_adapter.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(ai_input, ensure_ascii=False)},
                    {"role": "assistant", "content": json.dumps(ai, ensure_ascii=False)},
                    {"role": "user", "content": retry_user},
                ],
                timeout=Config.QWEN_TIMEOUT,
            )
        except Exception:
            logger.exception("[AI判词] 重写 Qwen 调用异常，维持模板兜底")
            break
        if not body_r:
            break
        content_r: str = body_r.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content_r:
            break
        try:
            ai_r: dict[str, Any] = _parse_ai_json(content_r)
        except Exception:
            logger.exception("[AI判词] 重写 JSON 解析失败，维持模板兜底")
            break
        if not ai_r:
            break
        failures = _merge_ai_verdicts(display, ai_r, ai_input)["failures"]
        logger.info(f"[AI判词] 第 {retries} 次重写完成 耗时={time.time() - t_retry:.1f}s "
                    f"仍失败={len(failures)} 个字段")

    # 9. 标记 AI 生成（下游 _run 据此判断是否落库 display_i18n）
    display["_aiGenerated"] = lang

    return display


def _build_retry_feedback(failures: list[dict[str, Any]]) -> str:
    """把校验失败清单拼成给 AI 的英文重写反馈。

    每个失败字段列出：字段名 + AI 上版原文 + 错误原因。
    AI 据此修正对应字段，其余字段保持上版内容，重新输出完整 JSON。
    """
    lines: list[str] = [
        "Your previous output failed validation. Fix ONLY the fields with errors below.",
        "For each field, use the correct numbers/values that already exist in the data.",
        "Keep all other fields identical to your previous output.",
        "Re-output the COMPLETE JSON, do not omit any field.",
        "",
    ]
    for f in failures:
        lines.append(f"- field: {f['field']}")
        lines.append(f"  your previous text: {str(f.get('text', ''))[:200]}")
        for e in f.get("errors", []):
            lines.append(f"  error: {e}")
    return "\n".join(lines)


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
) -> dict[str, Any]:
    """AI 输出合并：翻译 title + supplierName + 判词语优化。

    判词逐字段校验：数字必须与 dimensions 数据一致，禁止表述不得出现。
    校验失败 → 该字段保留 glossary 模板，不阻塞其他字段。
    返回 {"failures": [{field, text, errors}, ...]} 供调用方决定是否带反馈重写。
    """
    failures: list[dict[str, Any]] = []
    # title（基础检查：非空 + 长度合理）
    title: str = str(ai.get("translated_title", ""))
    if title and title.strip() and len(title.strip()) > 3:
        display["title"] = _strip_cjk(title.strip())

    # 公司名翻译（基础检查：非空 + 长度合理）→ factory.supplierName + supplierEval.companyName 同步
    sname: str = _strip_cjk(str(ai.get("translated_supplier_name", "")))
    if sname and sname.strip() and len(sname.strip()) > 1:
        if "factory" in display:
            display["factory"]["supplierName"] = sname.strip()
        if "supplierEval" in display and isinstance(display["supplierEval"], dict):
            display["supplierEval"]["companyName"] = sname.strip()

    # 排名标签翻译（1688 原始中文 → 目标语言）→ factory.rankText（emoji 前缀与 glossary emoji_rank 一致）
    rank_t: str = _strip_cjk(str(ai.get("translated_rank", "")))
    if rank_t and rank_t.strip():
        if "factory" in display and isinstance(display["factory"], dict):
            display["factory"]["rankText"] = "🏆 " + rank_t.strip()

    # 判词语优化（逐字段校验，失败 → 保留 glossary 模板）
    _verdict_fields: list[tuple[str, str, tuple[str, ...]]] = [
        ("product_verdict", "productEval", ("product",)),
        ("supplier_verdict", "supplierEval", ("supplier",)),
        # 综合判词同样防编造：数字必须能在品/厂维度数据里对上
        ("summary_verdict", "summaryLine", ("product", "supplier")),
    ]
    for ai_key, display_key, dim_sections in _verdict_fields:
        ai_text: str = str(ai.get(ai_key, ""))
        if not ai_text or not ai_text.strip():
            continue
        errors: list[str] = validate_ai_output(ai_text, [], ai_input, dim_sections)
        if not errors:
            if display_key in display and isinstance(display[display_key], dict):
                display[display_key]["verdict"] = ai_text.strip()
                # summary_verdict 同时写 reason：前端 s2Reason 显示 reason，verdict 不渲染
                if ai_key == "summary_verdict":
                    display[display_key]["reason"] = ai_text.strip()
        else:
            failures.append({"field": ai_key, "text": ai_text, "errors": errors})
            logger.warning(
                f"[AI判词] {ai_key} 校验失败，降级 glossary | "
                f"text={ai_text[:80]}... errors={errors}"
            )

    return {"failures": failures}
