"""AI 判词输入/输出纯函数 — 规则引擎 + Qwen 之间的桥梁。

职责：
- pack_ai_input():    评估结果 + mapped → Qwen 结构化 JSON 输入
- validate_ai_output(): AI 输出校验（数字精确 + 禁止表述 + tier 走样检测）

纯函数模块，零外部依赖。IO 仅在模块导入时读 JSON 配置一次。
被 services/ai_verdict_svc.py 的 build_with_ai() 调用。
"""

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

# ---- 加载配置 JSON ----
_HERE = Path(__file__).parent
with open(_HERE.parent / "data" / "glossary.json", "r", encoding="utf-8") as _f:
    _GL = json.load(_f)
with open(_HERE / "verdict_prompts.json", "r", encoding="utf-8") as _f:
    _VP = json.load(_f)


def _gl(key: str, lang: str, default: str = "") -> str:
    """glossary.json 查表。"""
    entry: Any = _GL.get(key, {})
    if not isinstance(entry, dict):
        return default or key
    d: dict[str, str] = cast(dict[str, str], entry)
    en_value: str = d.get("en", default or key)
    return d.get(lang, en_value)


def _fmt_dim_num(n: Any) -> str:
    """维度数字格式化：8900 → '8,900'，67.5 → '67.5'。"""
    if n is None:
        return "0"
    try:
        v: float = float(n)
        if v == int(v):
            return f"{int(v):,}"
        s: str = f"{v:,.1f}"
        return s.rstrip("0").rstrip(".") if "." in s else s
    except (ValueError, TypeError):
        return str(n)


# ====================================================================
# 公开 API
# ====================================================================

__all__ = ["pack_ai_input", "validate_ai_output"]


# ====================================================================
# pack_ai_input — 打包 Qwen 输入
# ====================================================================


def pack_ai_input(
    product_raw: dict[str, Any],
    supplier_raw: dict[str, Any],
    summary_raw: dict[str, Any],
    mapped: dict[str, Any],
    lang: str,
    money: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """打包 AI 判词输入：评估结果 + mapped → Qwen 结构化 JSON。

    所有 1688 原始数据走 JSON key-value 传递（to_translate），
    不拼入自然语言 prompt，防止 prompt 注入。

    Args:
        product_raw: evaluate_product() 输出
        supplier_raw: evaluate_supplier() 输出
        summary_raw: evaluate_summary() 输出
        mapped: product_mapper.map_raw() 输出
        lang: 目标语言代码
        money: 本地货币配置 {symbol, per_cny, decimals}，None 保持 ¥

    Returns:
        结构化 JSON，可直接 json.dumps 后作为 Qwen user message。
    """
    p_tier: str = str(product_raw.get("tier", "watch"))
    s_tier: str = str(supplier_raw.get("tier", "caution"))
    summary_tier: str = str(summary_raw.get("tier", "wait_data"))

    return {
        "lang": lang,
        "conclusion": {
            "product_tier": p_tier,
            "supplier_tier": s_tier,
            "summary_tier": summary_tier,
            "tone": _derive_tone(p_tier),
            "product_grade": str(product_raw.get("grade", "")),
            "supplier_grade": str(supplier_raw.get("grade", "")),
            "summary_grade": str(summary_raw.get("grade", "")),
        },
        "currency": str(money["symbol"]) if money else "¥",
        "must_mention": _pack_product_must_mention(product_raw, mapped, money),
        "supplier_must_mention": _pack_supplier_must_mention(supplier_raw),
        "must_not_say": _pack_product_must_not_say(p_tier, product_raw),
        "supplier_must_not_say": _pack_supplier_must_not_say(s_tier, supplier_raw),
        "action": _pack_action(product_raw, supplier_raw),
        "context": _pack_context(mapped, supplier_raw, lang, money),
        "dimensions": _pack_dimensions(product_raw, supplier_raw, money),
        "to_translate": {
            "title": str(mapped.get("title", "")),
            "supplier_name": str(mapped.get("supplierName", "")),
            "rank": str(mapped.get("rankText", "")),
        },
    }


def _fmt_money(cny: float, money: dict[str, Any] | None) -> str:
    """人民币金额 → 目标货币字符串（判词内金额本地化）。money=None 时保持 ¥。"""
    if money is None:
        return f"¥{cny:.2f}"
    v: float = cny * float(money["per_cny"])
    decimals: int = int(money.get("decimals", 2))
    sym: str = str(money["symbol"])
    if decimals == 0:
        return f"{sym}{int(round(v)):,}"
    return f"{sym}{v:.{decimals}f}"


def _derive_tone(p_tier: str) -> str:
    """从产品 tier 推导判词语气。

    拨正后 tone 只看产品档（销量×门槛/退货）：trial 统一 positive_but_cautious，
    供应商强弱在综合层体现，不再影响产品判词语气。
    """
    if p_tier.startswith("go"):
        return "positive"
    if p_tier.startswith("trial"):
        return "positive_but_cautious"
    if p_tier.startswith("caution"):
        return "cautious"
    if p_tier.startswith("fatal"):
        return "negative"
    return "neutral"


# ---- must_mention builders ----

def _pack_product_must_mention(product_raw: dict[str, Any], mapped: dict[str, Any], money: dict[str, Any] | None = None) -> list[str]:
    """从产品评估提取 AI 判词必须提及的事实列表。"""
    signals: dict[str, Any] = product_raw.get("signals", {})
    items: list[str] = []

    sold = signals.get("sold")
    if sold is not None:
        items.append(f"sales: {sold} units (hot threshold: >1000, potential: >100)")

    repurchase = signals.get("repurchase")
    if repurchase is not None:
        items.append(f"repurchase rate: {repurchase}% (high threshold: >30%, baseline: >10%)")

    price = signals.get("display_price")
    moq = signals.get("moq")
    unit = str(signals.get("unit", ""))
    if price is not None and moq is not None:
        items.append(f"price: {_fmt_money(float(price), money)}/{unit}, MOQ: {moq} {unit}")

    positive = signals.get("positive")
    if positive is not None:
        items.append(f"positive review rate: {positive}% (excellent: ≥98%, good: ≥95%)")

    wanted = signals.get("wanted")
    if wanted is not None:
        items.append(f"want-buy count: {wanted} (high demand: >100, notable: >30)")

    risk_flag = signals.get("risk_flag")
    if risk_flag == "no_return":
        items.append("WARNING: no 7-day unconditional return — buyers bear return risk")

    if (repurchase is not None and repurchase > 30
            and (sold is None or sold <= 100)):
        items.append("ANOMALY: high repurchase rate but very low sales — "
                     "possible listing switch or review manipulation. "
                     "Check factory's other products.")

    return items


def _pack_supplier_must_mention(supplier_raw: dict[str, Any]) -> list[str]:
    """从供应商评估提取 AI 判词必须提及的事实列表。"""
    signals: dict[str, Any] = supplier_raw.get("signals", {})
    items: list[str] = []

    identity = str(signals.get("identity_strength", ""))
    flags = str(signals.get("d1", {}).get("data_key", ""))
    if identity == "strong":
        items.append(f"supplier identity: {flags} — verified manufacturer/super factory")
    elif identity == "medium":
        items.append("supplier identity: self-claimed factory, not externally verified")
    elif identity == "weak":
        items.append("supplier identity: TRADER/WHOLESALER — not a factory. "
                     "Markup and quality control risk.")

    cert_strength = str(signals.get("cert_strength", ""))
    cert_type = str(signals.get("cert_type", ""))
    if cert_strength == "strong" and cert_type:
        items.append(f"certification: {cert_type} — deep third-party verification passed")
    elif cert_strength == "medium" and cert_type:
        items.append(f"certification: {cert_type} — basic verification only")
    elif cert_strength == "weak":
        items.append("certification: NONE — no third-party quality audit. "
                     "Higher risk of quality issues.")

    years = signals.get("shop_years")
    if years is not None:
        items.append(f"shop age: {years} years (established: ≥3 yrs, new: <1 yr)")

    return items


# ---- must_not_say builders ----

def _pack_product_must_not_say(p_tier: str, product_raw: dict[str, Any]) -> list[str]:
    """根据产品 tier 生成禁止表述列表。"""
    items: list[str] = []

    if p_tier.startswith("fatal"):
        items.extend(["this product is recommended", "worth trying", "good product"])
    elif p_tier.startswith("watch"):
        items.extend(["strongly recommended", "proven bestseller", "go for it",
                       "confidently order"])
    elif p_tier.startswith("caution"):
        items.extend(["completely risk-free", "buy with full confidence", "no concerns"])

    signals: dict[str, Any] = product_raw.get("signals", {})
    if signals.get("sold") is None:
        items.append("proven sales record")
    if signals.get("repurchase") is None:
        items.extend(["high customer loyalty", "verified repurchase rate"])

    return items


def _pack_supplier_must_not_say(s_tier: str, supplier_raw: dict[str, Any]) -> list[str]:
    """根据供应商 tier 生成禁止表述列表。"""
    signals: dict[str, Any] = supplier_raw.get("signals", {})
    items: list[str] = []

    identity = str(signals.get("identity_strength", ""))
    cert = str(signals.get("cert_strength", ""))
    years_strength = str(signals.get("years_strength", ""))

    if identity == "weak":
        items.extend(["reliable factory", "trusted manufacturer", "direct factory source",
                       "factory-direct", "manufacturer direct", "source factory"])
    elif identity == "medium":
        items.extend(["verified factory", "certified manufacturer", "audited factory"])

    if cert == "weak":
        items.extend(["quality certified", "third-party verified quality", "quality assured",
                       "quality guaranteed", "QC passed"])

    if years_strength == "weak":
        items.extend(["established supplier", "long operating history",
                       "experienced supplier", "well-established"])

    if s_tier.startswith("fatal_"):
        items.extend(["supplier can be trusted", "safe to order", "reliable supplier"])

    return items


# ---- action ----

def _pack_action(product_raw: dict[str, Any], supplier_raw: dict[str, Any]) -> str:
    """根据产品 tier 推导推荐行动（供应商短板通过 action_key 在上方优先处理）。

    防诱导铁律：动作一律条件式（if/to …），禁祈使命令与催促，只指下一步验证点。
    """
    p_tier: str = str(product_raw.get("tier", "watch"))

    s_verdict: Any = supplier_raw.get("verdict", {})
    if isinstance(s_verdict, dict):
        sv = cast(dict[str, Any], s_verdict)
        action_key: str = str(sv.get("params", {}).get("action_key", ""))
        action_map: dict[str, str] = {
            "supp_action_ok": "Product and supplier both check out. "
                              "To move forward: sample to confirm specs, then scale.",
            "supp_action_compare": "Supplier is a trader. If committing, "
                                   "compare prices with 2-3 other suppliers — markup is the risk.",
            "supp_action_inspect": "Supplier lacks certification. If ordering bulk, "
                                   "request detailed photos or inspection first — unverified quality is the risk.",
            "supp_action_compare_inspect": "Supplier is an uncertified trader. If proceeding, "
                                           "compare alternatives and inspect samples — both markup and quality are risks.",
            "supp_action_check_delivery": "Supplier is relatively new. If partnering, "
                                          "verify delivery reliability with a small trial order — stockouts are the risk.",
        }
        if action_key and action_key in action_map:
            return action_map[action_key]

    if p_tier.startswith("go"):
        return "Product and supplier both check out. If moving forward, sample to confirm before scaling."
    if p_tier.startswith("trial"):
        return "If trying this, order 2-3 samples and confirm the goods match the photos before bulk."
    if p_tier.startswith("caution"):
        return "If considering it, watch the sales trend or find a similar product with a lower MOQ before committing."
    if p_tier.startswith("watch"):
        return "Current signals aren't enough to act on — more data is needed before deciding."
    if p_tier.startswith("fatal"):
        return "If anything, skip this product and look for alternatives with better fundamentals."
    return "If proceeding, verify with a small sample before committing to larger quantities."


# ---- context ----

def _pack_context(
    mapped: dict[str, Any],
    supplier_raw: dict[str, Any],
    lang: str,
    money: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建 AI 上下文：试错成本 + 供应商摘要 + 市场备注。

    trial_cost 的风险等级按人民币阈值判断（试错成本定义不变），
    金额显示按 money 换成本地货币。
    """
    price_cny_raw: Any = mapped.get("priceCNY")
    price_cny: dict[str, Any] = cast(dict[str, Any], price_cny_raw) if isinstance(price_cny_raw, dict) else {}
    low_price: float = float(price_cny.get("low", 0)) if price_cny else 0.0
    moq_val: Any = mapped.get("moq")
    try:
        moq: int = int(moq_val) if moq_val else 0
    except (ValueError, TypeError):
        moq = 0
    unit: str = str(mapped.get("unit", ""))

    if low_price > 0 and moq > 0:
        total: float = low_price * moq
        if total < 50:
            trial_cost: str = (f"Very low risk — {_fmt_money(total, money)} minimum order "
                              f"({moq} {unit} × {_fmt_money(low_price, money)})")
        elif total < 200:
            trial_cost: str = (f"Moderate risk — {_fmt_money(total, money)} minimum order "
                              f"({moq} {unit} × {_fmt_money(low_price, money)})")
        else:
            trial_cost: str = (f"Higher barrier — {_fmt_money(total, money)} minimum order "
                              f"({moq} {unit} × {_fmt_money(low_price, money)})")
    else:
        trial_cost = "Unknown — price or MOQ data incomplete"

    signals: dict[str, Any] = supplier_raw.get("signals", {})
    identity_map: dict[str, str] = {
        "strong": "verified factory", "medium": "self-claimed factory",
        "weak": "trader/wholesaler",
    }
    cert_map: dict[str, str] = {
        "strong": "deeply certified", "medium": "basically certified",
        "weak": "uncertified",
    }
    identity_text: str = identity_map.get(
        str(signals.get("identity_strength", "")), "unknown identity")
    cert_text: str = cert_map.get(
        str(signals.get("cert_strength", "")), "unknown certification")
    years_val: Any = signals.get("shop_years")
    years_text: str = f"{years_val}yr" if years_val is not None else "unknown age"
    supplier_summary: str = f"{identity_text}, {cert_text}, {years_text}"

    market_note: str = str(_VP.get("market_notes", {}).get(lang, ""))

    return {
        "trial_cost": trial_cost,
        "supplier_summary": supplier_summary,
        "market_note": market_note,
    }


# ---- dimensions ----

def _pack_dimensions(
    product_raw: dict[str, Any],
    supplier_raw: dict[str, Any],
    money: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """将 evaluator 维度转为 AI 可读的简化格式（价格按 money 本地化）。"""
    product_dims: list[dict[str, Any]] = []
    for dim in product_raw.get("dimensions", []):
        if not isinstance(dim, dict):
            continue
        d = cast(dict[str, Any], dim)
        score: int = int(d.get("score", 0))
        if score == 0:
            continue  # no-data 维度不打包，省 token（低质/数据不足商品维度多为空）
        product_dims.append({
            "key": str(d.get("key", "")),
            "signal": {3: "positive", 2: "neutral", 1: "negative"}.get(score, "unknown"),
            "label": _gl(str(d.get("name_key", "")), "en"),
            "data": _dim_data_text(d, money),
            "ref": _dim_ref_text(d),
        })

    supplier_dims: list[dict[str, Any]] = []
    supplier_signals: dict[str, Any] = supplier_raw.get("signals", {})
    for dim in supplier_raw.get("dimensions", []):
        if not isinstance(dim, dict):
            continue
        d = cast(dict[str, Any], dim)
        score_s: int = int(d.get("score", 0))
        if score_s == 0:
            continue  # no-data 维度不打包，省 token
        data_s: str = _dim_data_text(d)
        if not data_s and str(d.get("key")) == "d2":
            cert_type_raw: str = str(supplier_signals.get("cert_type", ""))
            if cert_type_raw:
                data_s = cert_type_raw
        supplier_dims.append({
            "key": str(d.get("key", "")),
            "signal": {3: "positive", 2: "neutral", 1: "negative"}.get(score_s, "unknown"),
            "label": _gl(str(d.get("name_key", "")), "en"),
            "data": data_s,
            "ref": _dim_ref_text(d),
        })

    return {"product": product_dims, "supplier": supplier_dims}


def _dim_data_text(dim: dict[str, Any], money: dict[str, Any] | None = None) -> str:
    """从维度 dict 提取人类可读的数据文本（English，供 AI 参考；价格按 money 本地化）。"""
    score: int = int(dim.get("score", 0))
    if score == 0:
        return "no data"

    data_key: str = str(dim.get("data_key", ""))
    if data_key:
        return _gl(data_key, "en", data_key)

    data_fmt: str = str(dim.get("data_fmt", ""))
    data_num: Any = dim.get("data_num")
    if data_fmt and data_num is not None:
        try:
            return _gl(data_fmt, "en").format(n=_fmt_dim_num(data_num))
        except (KeyError, ValueError):
            return str(data_num)

    data_params: dict[str, Any] = dim.get("data_params") or {}
    if data_params:
        parts: list[str] = []
        for k, v in data_params.items():
            if k == "unit":
                parts.append(_gl(f"unit_{v}", "en", str(v)))
            elif k == "price" and isinstance(v, (int, float)):
                parts.append(_fmt_money(float(v), money))
            elif isinstance(v, (int, float)):
                parts.append(f"{v}")
            else:
                parts.append(str(v))
        return ", ".join(parts) if parts else ""

    data_text: str = str(dim.get("data_text", ""))
    if data_text:
        return data_text

    return ""


def _dim_ref_text(dim: dict[str, Any]) -> str:
    """从维度 dict 提取参考阈值文本（English，供 AI 参考）。"""
    ref_fmt: str = str(dim.get("ref_fmt", ""))
    ref_num: Any = dim.get("ref_num")
    if ref_fmt and ref_num is not None:
        try:
            return _gl(ref_fmt, "en").format(n=_fmt_dim_num(ref_num))
        except (KeyError, ValueError):
            return ""

    ref_params: dict[str, Any] = dim.get("ref_params") or {}
    if ref_params:
        parts: list[str] = []
        for k, v in ref_params.items():
            if k == "unit":
                parts.append(_gl(f"unit_{v}", "en", str(v)))
            elif isinstance(v, (int, float)):
                parts.append(f"{v}")
            else:
                parts.append(str(v))
        return ", ".join(parts) if parts else ""

    return ""


# ====================================================================
# validate_ai_output — 校验 AI 输出
# ====================================================================


def validate_ai_output(
    ai_text: str,
    must_mention: list[str],
    ai_input: dict[str, Any],
    dimension_sections: tuple[str, ...] = ("product", "supplier"),
) -> list[str]:
    """校验 AI 判词输出：关键数字精确匹配 + 禁止表述未出现。

    返回错误清单（英文，供重试反馈喂回 AI）；空列表 = 通过。
    非空 → 调用方将该字段降级为模板判词，或带反馈让 AI 重写一次。

    校验规则（按优先级）：
    1. AI 文本中的数字必须能在指定 section 维度数据(data+ref)中精确对上（防编造）
    2. must_not_say 中的禁止表述不得出现（大小写不敏感，跨 section 全量检查）
    3. 判词禁止含中文字符（CJK）— 非 zh 判词必须纯母语，混中文触发重写/降级

    Args:
        ai_text: AI 生成的单个字段文本（如 product_verdict）
        must_mention: 该字段对应的必须提及列表（保留参数，实际校验走 dimensions）
        ai_input: pack_ai_input() 完整输出
        dimension_sections: 要检查数字的维度 section，默认全部。
            product_verdict → ("product",)
            supplier_verdict → ("supplier",)
            summary_verdict → ()（综合结论不校验数字，只查禁止表述）
    """
    errors: list[str] = []
    if not ai_text or not ai_text.strip():
        return ["Empty verdict text"]

    # 规则 1：防编造 — AI 文本里的数字必须能在数据源维度(data+ref)里对上
    # 方向反转：从「数据源数字必须全出现」改为「AI 数字必须真实存在」，查 AI 有没有编造数据源没有的数字
    if dimension_sections:
        source_text: str = " ".join(
            f"{dim.get('data', '')} {dim.get('ref', '')}"
            for section in dimension_sections
            for dim in ai_input.get("dimensions", {}).get(section, [])
        )
        for n in re.findall(r"\b\d[\d.,]*\d\b|\b\d\b", ai_text):
            if len(n) <= 1:
                continue
            # 平台名 1688 非业务数字，跳过防编造检查（与 verify_verdicts.py 的 SKIP_NUMS 对齐）
            try:
                if _norm_num(n) == Decimal(1688):
                    continue
            except (InvalidOperation, ValueError):
                pass
            if not _number_appears(source_text, n):
                errors.append(
                    f'Number "{n}" is not in the source data. '
                    "Only use numbers provided in the data."
                )

    # 规则 2：禁止表述检查（跨 section 全量检查）
    for key in ("must_not_say", "supplier_must_not_say"):
        for forbidden in ai_input.get(key, []):
            if forbidden.lower() in ai_text.lower():
                errors.append(
                    f'Forbidden phrase "{forbidden}" must not appear in the verdict.'
                )

    # 规则 3：非中文判词禁止含中文字符（zh 走模板不经过此校验，无需区分语言）
    if re.search(r"[一-鿿]", ai_text):
        errors.append(
            "Text contains Chinese characters — the verdict must be written "
            "entirely in the target language (English/Vietnamese/Thai)."
        )

    # 规则 4：结论词锁 grade — 首词必须匹配该字段档位对应的结论词（方法论 §三 标准1）
    errors.extend(_check_conclusion_word(ai_text, ai_input, dimension_sections))

    # 规则 5：恰好 ≤3 句 + 每句不超 90 字（方法论 §三 标准6）
    errors.extend(_check_sentence_structure(ai_text))

    # 规则 6：综合判词禁祈使/催促（方法论 §四·五）
    errors.extend(_check_summary_urgency(ai_text, ai_input, dimension_sections))

    # 规则 7：综合判词数字数量 — 至少 2 产品数 + 1 供应商数（数据不足自动放宽）。
    # 仅真实 summary 调用（("product","supplier")）触发；() 表示不查数字（测试用）。
    if dimension_sections == ("product", "supplier"):
        errors.extend(_check_summary_numbers(ai_text, ai_input))

    return errors


# ---- 结构校验辅助 ----

def _field_for_sections(dimension_sections: tuple[str, ...]) -> str:
    """维度 section → 判词字段名（用于取对应档位 + 触发综合专属规则）。"""
    if dimension_sections == ("supplier",):
        return "supplier"
    if dimension_sections == ("product",):
        return "product"
    return "summary"  # ("product", "supplier") 或 ()（综合不查数字）


def _check_conclusion_word(ai_text: str, ai_input: dict[str, Any], dimension_sections: tuple[str, ...]) -> list[str]:
    """规则4：判词首词必须匹配档位结论词，禁止 AI 自由选结论（待落地①）。"""
    field: str = _field_for_sections(dimension_sections)
    conclusion: dict[str, Any] = cast(dict[str, Any], ai_input.get("conclusion")) or {}
    grade: str = str(conclusion.get(f"{field}_grade", ""))
    lang: str = str(ai_input.get("lang", "en"))
    structure: dict[str, Any] = cast(dict[str, Any], _VP.get("_structure")) or {}
    cw: dict[str, Any] = cast(dict[str, Any], structure.get("conclusion_words")) or {}
    by_lang: dict[str, Any] = cast(dict[str, Any], cw.get(lang)) or {}
    words: list[str] = cast(list[str], by_lang.get(grade)) or []
    if not grade or not words:
        return []  # 无档位或该语言无词表 → 无法判断，跳过（宽松兜底）

    low: str = ai_text.strip().lower()
    for w in words:
        if low.startswith(str(w).lower()):
            return []
    return [
        f'Verdict must open with a conclusion word matching grade "{grade}" '
        f'(one of: {", ".join(words)}).'
    ]


def _check_sentence_structure(ai_text: str) -> list[str]:
    """规则5：≤3 句 + 总长 ≤200 字（截句按句末标点后跟空白，避免拆分千分位/小数）。

    用总长而非每句长：越/泰语天然更啰嗦，泰语模板常无句末标点，每句阈值会误杀正确模板。
    """
    cfg: dict[str, Any] = _VP.get("_structure") or {}
    max_s: int = int(cfg.get("max_sentences", 3))
    max_total: int = int(cfg.get("max_total_chars", 200))
    parts: list[str] = [p.strip() for p in re.split(r"(?<=[.!?。！？])\s+", ai_text) if p.strip()]
    errors: list[str] = []
    if len(parts) > max_s:
        errors.append(f"Verdict has {len(parts)} sentences; max {max_s}.")
    if len(ai_text) > max_total:
        errors.append(f"Verdict too long ({len(ai_text)} chars); max {max_total}.")
    return errors


def _check_summary_urgency(ai_text: str, ai_input: dict[str, Any], dimension_sections: tuple[str, ...]) -> list[str]:
    """规则6：仅综合判词，禁命令/催促语（方法论 §四·五）。"""
    if _field_for_sections(dimension_sections) != "summary":
        return []
    lang: str = str(ai_input.get("lang", "en"))
    structure: dict[str, Any] = cast(dict[str, Any], _VP.get("_structure")) or {}
    up: dict[str, Any] = cast(dict[str, Any], structure.get("urgency_patterns")) or {}
    patterns: list[str] = cast(list[str], up.get(lang)) or []
    low: str = ai_text.lower()
    errors: list[str] = []
    for p in patterns:
        if str(p).lower() in low:
            errors.append(f'Urgency/imperative phrase "{p}" is not allowed in the summary.')
    return errors


def _check_summary_numbers(ai_text: str, ai_input: dict[str, Any]) -> list[str]:
    """规则7：综合判词数字数量 — 至少 2 产品数 + 1 供应商数（数据不足自动放宽）。

    每个「含数字的维度」计一个可用数字（取 data 首个数字，ref 阈值不计数）。
    need = min(需求数, 可用数)：数据缺失时自动放宽，不误杀缺数据的品。
    """
    dims: dict[str, Any] = ai_input.get("dimensions") or {}
    product_nums: list[str] = _dim_first_numbers(dims.get("product", []))
    supplier_nums: list[str] = _dim_first_numbers(dims.get("supplier", []))
    need_p: int = min(2, len(product_nums))
    need_s: int = min(1, len(supplier_nums))

    found_p: int = sum(1 for n in product_nums if _number_appears(ai_text, n))
    found_s: int = sum(1 for n in supplier_nums if _number_appears(ai_text, n))

    errors: list[str] = []
    if found_p < need_p:
        errors.append(f"Summary must include at least {need_p} product numbers (found {found_p}).")
    if found_s < need_s:
        errors.append(f"Summary must include at least {need_s} supplier number(s) (found {found_s}).")
    return errors


def _dim_first_numbers(dims: list[Any]) -> list[str]:
    """从每个维度的 data 文本提取首个数字（ref 阈值不计数，只算主数据数字）。"""
    nums: list[str] = []
    for d in dims:
        if not isinstance(d, dict):
            continue
        m: re.Match[str] | None = re.search(r"\d[\d.,]*\d|\d", str(d.get("data", "")))
        if m:
            nums.append(m.group(0))
    return nums


def _number_appears(text: str, num_str: str) -> bool:
    """检查 num_str 的数值是否出现在 text 中（容忍本地化格式差异）。

    核心：数值等价 —— 把 num_str 和 text 中的数字都归一化成标准数值，
    任一相等即通过。兼容英文（逗号千分位/点小数）与越南语/泰语（点千分位/逗号小数）。
    例："3,50"（越南语 3.5）与源数据 "3.5" 等价；"5.915"（越南语 5915）与 "5,915" 等价。
    """
    if not num_str:
        return True
    if num_str in text:
        return True

    try:
        target: Decimal = _norm_num(num_str)
    except (InvalidOperation, ValueError):
        return num_str.lower() in text.lower()

    for m in re.findall(r"\d[\d.,]*\d|\d", text):
        try:
            if _norm_num(m) == target:
                return True
        except (InvalidOperation, ValueError):
            continue
    return False


def _norm_num(s: str) -> Decimal:
    """数字字符串 → 标准数值，兼容英文/越南语/泰语分隔符。

    判断规则：最后一个分隔符（,/.）后的位数 < 3 → 它是小数点，前面其它分隔符是千分位；
    否则全部当千分位去掉。可覆盖：
      "3,50"→3.5  "3.5"→3.5  "5.915"→5915  "5,915"→5915  "1.000"→1000  "63"→63
    """
    digits: str = re.sub(r"[^\d.,]", "", s.strip())
    if not digits:
        raise ValueError(s)
    last_sep: int = max(digits.rfind(","), digits.rfind("."))
    if last_sep >= 0 and len(digits[last_sep + 1:]) < 3:
        int_part: str = digits[:last_sep].replace(",", "").replace(".", "")
        return Decimal(f"{int_part}.{digits[last_sep + 1:]}")
    return Decimal(digits.replace(",", "").replace(".", ""))
