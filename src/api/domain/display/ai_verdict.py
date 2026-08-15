"""AI 判词输入/输出纯函数 — 规则引擎 + Qwen 之间的桥梁。

职责：
- pack_ai_input():    评估结果 + mapped → Qwen 结构化 JSON 输入
- validate_ai_output(): AI 输出校验（数字精确 + 禁止表述 + tier 走样检测）

纯函数模块，零外部依赖。IO 仅在模块导入时读 JSON 配置一次。
被 services/ai_verdict_svc.py 的 build_with_ai() 调用。
"""

import json
import re
from pathlib import Path
from typing import Any, cast

# ---- 加载配置 JSON ----
_HERE = Path(__file__).parent
with open(_HERE.parent / "data" / "glossary.json", "r", encoding="utf-8") as _f:
    _GL = json.load(_f)
with open(_HERE / "verdict_prompts.json", "r", encoding="utf-8") as _f:
    _VP = json.load(_f)


def _gl(key: str, lang: str, default: str = "") -> str:
    """term_glossary.json 查表。"""
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

    Returns:
        结构化 JSON，可直接 json.dumps 后作为 Qwen user message。
    """
    p_tier: str = str(product_raw.get("tier", "watch"))
    s_tier: str = str(supplier_raw.get("tier", "caution"))
    summary_tier: str = str(summary_raw.get("tier", "wait_data"))

    return {
        "conclusion": {
            "product_tier": p_tier,
            "supplier_tier": s_tier,
            "summary_tier": summary_tier,
            "tone": _derive_tone(p_tier),
        },
        "must_mention": _pack_product_must_mention(product_raw, mapped),
        "supplier_must_mention": _pack_supplier_must_mention(supplier_raw),
        "must_not_say": _pack_product_must_not_say(p_tier, product_raw),
        "supplier_must_not_say": _pack_supplier_must_not_say(s_tier, supplier_raw),
        "action": _pack_action(product_raw, supplier_raw),
        "context": _pack_context(mapped, supplier_raw, lang),
        "dimensions": _pack_dimensions(product_raw, supplier_raw),
        "to_translate": {
            "title": str(mapped.get("title", "")),
            "supplier_name": str(mapped.get("supplierName", "")),
        },
    }


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

def _pack_product_must_mention(product_raw: dict[str, Any], mapped: dict[str, Any]) -> list[str]:
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
        items.append(f"price: ¥{price:.2f}/{unit}, MOQ: {moq} {unit}")

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
    """根据产品 tier 推导推荐行动（供应商短板通过 action_key 在上方优先处理）。"""
    p_tier: str = str(product_raw.get("tier", "watch"))

    s_verdict: Any = supplier_raw.get("verdict", {})
    if isinstance(s_verdict, dict):
        sv = cast(dict[str, Any], s_verdict)
        action_key: str = str(sv.get("params", {}).get("action_key", ""))
        action_map: dict[str, str] = {
            "supp_action_ok": "Product and supplier both check out — "
                              "proceed with normal sample order then scale.",
            "supp_action_compare": "Supplier is a trader — compare prices with "
                                    "2-3 other suppliers before committing.",
            "supp_action_inspect": "Supplier lacks certification — request detailed "
                                    "photos or inspection before bulk order.",
            "supp_action_compare_inspect": "Supplier is an uncertified trader — "
                                            "compare alternatives AND inspect samples thoroughly.",
            "supp_action_check_delivery": "Supplier is relatively new — verify delivery "
                                           "reliability with a small trial order first.",
        }
        if action_key and action_key in action_map:
            return action_map[action_key]

    if p_tier.startswith("go"):
        return ("Product and supplier both check out — "
                "sample to confirm, then scale with confidence.")
    if p_tier.startswith("trial"):
        return ("Order 2-3 samples to verify quality before committing to bulk. "
                "Confirm the goods match the photos first.")
    if p_tier.startswith("caution"):
        return ("Watch the sales trend or find a similar product with a lower "
                "minimum order before committing.")
    if p_tier.startswith("watch"):
        return "Wait for more data — current signals aren't enough to act on."
    if p_tier.startswith("fatal"):
        return "Skip this product — look for alternatives with better fundamentals."
    return "Verify with a small sample order before committing to larger quantities."


# ---- context ----

def _pack_context(
    mapped: dict[str, Any],
    supplier_raw: dict[str, Any],
    lang: str,
) -> dict[str, Any]:
    """构建 AI 上下文：试错成本 + 供应商摘要 + 市场备注。"""
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
            trial_cost: str = (f"Very low risk — ¥{total:.2f} minimum order "
                              f"({moq} {unit} × ¥{low_price:.2f}) = under USD $7")
        elif total < 200:
            trial_cost: str = (f"Moderate risk — ¥{total:.2f} minimum order "
                              f"({moq} {unit} × ¥{low_price:.2f})")
        else:
            trial_cost: str = (f"Higher barrier — ¥{total:.2f} minimum order "
                              f"({moq} {unit} × ¥{low_price:.2f})")
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
) -> dict[str, Any]:
    """将 evaluator 维度转为 AI 可读的简化格式。"""
    product_dims: list[dict[str, Any]] = []
    for dim in product_raw.get("dimensions", []):
        if not isinstance(dim, dict):
            continue
        d = cast(dict[str, Any], dim)
        score: int = int(d.get("score", 0))
        product_dims.append({
            "key": str(d.get("key", "")),
            "signal": {3: "positive", 2: "neutral", 1: "negative"}.get(score, "unknown"),
            "label": _gl(str(d.get("name_key", "")), "en"),
            "data": _dim_data_text(d),
            "ref": _dim_ref_text(d),
        })

    supplier_dims: list[dict[str, Any]] = []
    supplier_signals: dict[str, Any] = supplier_raw.get("signals", {})
    for dim in supplier_raw.get("dimensions", []):
        if not isinstance(dim, dict):
            continue
        d = cast(dict[str, Any], dim)
        score_s: int = int(d.get("score", 0))
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


def _dim_data_text(dim: dict[str, Any]) -> str:
    """从维度 dict 提取人类可读的数据文本（English，供 AI 参考）。"""
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
) -> bool:
    """校验 AI 判词输出：关键数字精确匹配 + 禁止表述未出现。

    任一规则不过 → False → 调用方将该字段降级为模板判词。

    校验规则（按优先级）：
    1. 指定 section 维度数据中的关键数字必须精确出现在 AI 文本中（容忍本地化格式）
    2. must_not_say 中的禁止表述不得出现（大小写不敏感，跨 section 全量检查）

    Args:
        ai_text: AI 生成的单个字段文本（如 product_verdict）
        must_mention: 该字段对应的必须提及列表（保留参数，实际校验走 dimensions）
        ai_input: pack_ai_input() 完整输出
        dimension_sections: 要检查数字的维度 section，默认全部。
            product_verdict → ("product",)
            supplier_verdict → ("supplier",)
            summary_verdict → ("product", "supplier")
    """
    if not ai_text or not ai_text.strip():
        return False

    # 规则 1：维度数据数字精确检查（仅指定 section）
    for section in dimension_sections:
        for dim in ai_input.get("dimensions", {}).get(section, []):
            data_str: str = str(dim.get("data", ""))
            if not data_str or data_str == "no data":
                continue
            for n in re.findall(r"\b\d+(?:\.\d+)?\b", data_str):
                if len(n) <= 1:
                    continue
                if not _number_appears(ai_text, n):
                    return False

    # 规则 2：禁止表述检查（跨 section 全量检查）
    for key in ("must_not_say", "supplier_must_not_say"):
        for forbidden in ai_input.get(key, []):
            if forbidden.lower() in ai_text.lower():
                return False

    return True


def _number_appears(text: str, num_str: str) -> bool:
    """检查 num_str 的数值是否出现在 text 中（容忍本地化格式差异）。

    规则：
    - 精确匹配优先
    - 整数 >= 1000 → 尝试千分位变体（8,950 / 8.950 / 8 950）
    - 小数 → 尝试逗号小数点变体（67,5 = 67.5）
    - .0 结尾小数 → 也检查整数版（69.0 → 69）
    - 末招：数字序列匹配（格式化字符可插入）

    注意：用 "." in num_str 而非 n != int(n) 判断是否有小数位，
    因为 Python 中 69.0 == 69，无法区分 "69.0" 和 "69"。
    """
    if not num_str:
        return True

    if num_str in text:
        return True

    try:
        n: float = float(num_str)
    except ValueError:
        return num_str.lower() in text.lower()

    has_decimal: bool = "." in num_str
    int_n: int = int(n)

    # 整数 >= 1000 → 千分位变体
    if n == int_n and n >= 1000:
        variants: list[str] = [f"{int_n:,}"]
        variants.append(f"{int_n:,}".replace(",", "."))
        variants.append(f"{int_n:,}".replace(",", " "))
        for v in variants:
            if v in text:
                return True

    # 小数 → 本地化格式变体
    if has_decimal:
        for decimals in (1, 2):
            s: str = f"{n:.{decimals}f}"
            if s in text:
                return True
            comma_v: str = s.replace(".", ",")
            if comma_v in text:
                return True

        # .0 结尾（如 69.0）→ 也检查整数版（69），越南语常省略 .0
        if n == int_n:
            if str(int_n) in text:
                return True

    digits: str = "".join(c for c in num_str if c.isdigit())
    if len(digits) >= 3:
        pattern: str = r"(?<!\d)" + r"[\d.,\s]*".join(list(digits)) + r"(?!\d)"
        if re.search(pattern, text):
            return True

    return False
