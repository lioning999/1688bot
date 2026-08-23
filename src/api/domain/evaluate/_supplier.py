"""供应商评判引擎 — 3 维信号强度 → 黑箱检查 → 信号强度计数 → 6 规则 → 4 档 grade → 判词。

纯函数模块，零外部依赖。被 evaluator.py 导入，外部代码不应直接引用此文件。

依据：docs/技术-评分标准与标签体系.md §二
"""
from typing import Any

from domain.evaluate._base import (
    verdict, safe_int,
    SHOP_OLD, SHOP_NEW,
)


# ====================================================================
# 信号提取
# ====================================================================

def _supplier_signals(mapped: dict[str, Any]) -> dict[str, Any]:
    """提取 3 维信号强度（强/中等/弱/未知）。

    Returns:
        {identity_strength, cert_strength, years_strength,
         d1~d3 维度 dict, has_id, has_cert, has_years,
         identity_label, cert_type, shop_years}
    """
    flags: str = str(mapped.get("factoryFlags") or "")
    seller_type: str = str(mapped.get("sellerType") or "")
    cert_type_raw: Any = mapped.get("certType")
    # 字符串 "None" 来自 mapper 的 _safe_cert_type({}) → "None"，视为无认证
    cert_type: str = str(cert_type_raw) if (cert_type_raw and str(cert_type_raw) not in ("None", "")) else ""
    shop_years_val: Any = mapped.get("shop_years")
    shop_years: int | None = safe_int(shop_years_val)

    # ---- 身份强度 ----
    is_advanced: bool = (
        seller_type in ("super_factory", "flagship", "shili")
        or any(kw in flags for kw in ("超级工厂", "源头旗舰", "实力工厂", "实力商家"))
    )
    is_trader: bool = "非生产厂家" in flags or seller_type in ("trader",)
    is_factory: bool = (
        any(kw in flags for kw in ("生产厂家", "源头工厂", "工厂直供", "通品工厂"))
        and not is_trader
    )

    has_id: bool = bool(flags or seller_type)
    has_cert: bool = cert_type_raw is not None
    has_years: bool = shop_years is not None

    # 身份 → 维度 + 标签
    if not has_id:
        identity_strength, identity_label = "unknown", ""
        d1 = _dim_key("d1", 0, "🏭", "supp_dim_d1_name", "", "")
    elif is_advanced:
        identity_strength, identity_label = "strong", "supp_good_id_super"
        d1_data_key = _pick_first(flags, ("超级工厂", "源头旗舰", "实力工厂"), "实力商家")
        d1 = _dim_key("d1", 3, "🏭", "supp_dim_d1_name_adv", "supp_dim_d1_label_adv", d1_data_key)
    elif is_factory:
        identity_strength, identity_label = "medium", "supp_good_id_factory"
        d1 = _dim_key("d1", 2, "🏭", "supp_dim_d1_name_factory", "supp_dim_d1_label_factory", "工厂直供")
    else:
        identity_strength, identity_label = "weak", "supp_bad_id_trader"
        d1 = _dim_key("d1", 1, "⚠️", "supp_dim_d1_name_trader", "supp_dim_d1_label_trader", "贸易商")

    # ---- 认证强度 ----
    cert_lower: str = cert_type.lower()
    has_deep_cert: bool = any(kw in cert_lower for kw in ("深度验厂", "深度认证", "sgs", "tuv"))
    has_basic_cert: bool = bool(cert_type) and not has_deep_cert
    _cert_in_glossary: bool = cert_type in ("深度验厂", "实地认证", "第三方验厂", "SGS 实地认证")

    if not has_cert:
        cert_strength, cert_label = "unknown", ""
        d2 = _dim_key("d2", 0, "📋", "supp_dim_d2_name", "", "supp_dim_d2_data_no_cert")
    elif not cert_type:
        cert_strength, cert_label = "weak", "supp_bad_cert_none"
        d2 = _dim_key("d2", 1, "📋", "supp_dim_d2_name", "", "supp_dim_d2_data_no_cert")
    elif has_deep_cert:
        cert_strength, cert_label = "strong", "supp_good_cert_deep"
        d2 = _cert_dim("d2", 3, "supp_dim_d2_name_deep", "supp_dim_d2_label_deep",
                       cert_type, _cert_in_glossary)
    elif has_basic_cert:
        cert_strength, cert_label = "medium", "supp_good_cert_basic"
        d2 = _cert_dim("d2", 2, "supp_dim_d2_name", "", cert_type, _cert_in_glossary)
    else:
        cert_strength, cert_label = "weak", "supp_bad_cert_none"
        d2 = _dim_key("d2", 1, "📋", "supp_dim_d2_name", "", "supp_dim_d2_data_no_cert")

    # ---- 年限强度 ----
    if not has_years:
        years_strength, years_label = "unknown", ""
        d3 = _dim_fmt("d3", 0, "📅", "supp_dim_d3_name", "", "", None, "", None)
    elif shop_years >= SHOP_OLD:
        years_strength, years_label = "strong", "supp_good_years_old"
        d3 = _dim_fmt("d3", 3, "📅", "supp_dim_d3_name_old", "supp_dim_d3_label_old",
                      "supp_dim_d3_data_fmt", shop_years, "supp_dim_d3_ref_fmt", SHOP_OLD)
    elif shop_years >= SHOP_NEW:
        years_strength, years_label = "weak", "supp_bad_years_new"
        d3 = _dim_fmt("d3", 1, "📅", "supp_dim_d3_name", "",
                      "supp_dim_d3_data_fmt", shop_years, "supp_dim_d3_ref_fmt", SHOP_OLD)
    else:
        years_strength, years_label = "weak", "supp_bad_years_new"
        d3: dict[str, Any] = {"key": "d3", "score": 1, "icon": "📅",
              "name_key": "supp_dim_d3_name_new", "label_key": "supp_dim_d3_label_new",
              "data_key": "supp_dim_d3_data_short",
              "ref_fmt": "supp_dim_d3_ref_fmt", "ref_num": SHOP_OLD, "ref_params": {}}

    return {
        "identity_strength": identity_strength, "cert_strength": cert_strength, "years_strength": years_strength,
        "identity_label": identity_label, "cert_label": cert_label, "years_label": years_label,
        "cert_type": cert_type, "shop_years": shop_years,
        "has_id": has_id, "has_cert": has_cert, "has_years": has_years,
        "has_deep_cert": has_deep_cert, "has_basic_cert": has_basic_cert,
        "d1": d1, "d2": d2, "d3": d3,
    }


def _pick_first(text: str, candidates: tuple[str, ...], fallback: str) -> str:
    """从 text 中匹配第一个出现的候选词，返回对应 glossary key。"""
    for kw in candidates:
        if kw in text:
            return kw
    return fallback


def _dim_key(key: str, score: int, icon: str, name_key: str, label_key: str, data_key: str) -> dict[str, Any]:
    """构建 data_key 型维度 dict（身份/认证/退货）。"""
    return {"key": key, "score": score, "icon": icon,
            "name_key": name_key, "label_key": label_key,
            "data_key": data_key, "ref_fmt": "", "ref_params": {}}


def _dim_fmt(key: str, score: int, icon: str, name_key: str, label_key: str,
             data_fmt: str, data_num: int | None,
             ref_fmt: str = "", ref_num: int | None = None) -> dict[str, Any]:
    """构建 data_fmt 型维度 dict（年限）。"""
    return {"key": key, "score": score, "icon": icon,
            "name_key": name_key, "label_key": label_key,
            "data_fmt": data_fmt, "data_num": data_num,
            "ref_fmt": ref_fmt, "ref_num": ref_num}


def _cert_dim(key: str, score: int, name_key: str, label_key: str,
              cert_type: str, in_glossary: bool) -> dict[str, Any]:
    """构建认证维度 dict，区分 glossary key 和 ASCII 透传。"""
    data_key: str = cert_type if in_glossary else ""
    data_text: str = cert_type.upper() if (cert_type.isascii() and not in_glossary) else ""
    return {"key": key, "score": score, "icon": "📋",
            "name_key": name_key, "label_key": label_key,
            "data_key": data_key, "data_text": data_text,
            "ref_fmt": "", "ref_params": {}}


# ====================================================================
# 黑箱检查 + 数据不足
# ====================================================================

def _supplier_fatal(signals: dict[str, Any]) -> dict[str, Any] | None:
    """黑箱检查：身份 + 认证 + 年限 全空 → 致命（别碰）。"""
    if not signals["has_id"] and not signals["has_cert"] and not signals["has_years"]:
        return {
            "score": 0, "max_score": 9,
            "grade": "bad", "tier": "fatal_blackbox",
            "summary": verdict("supp_summary_fatal"),
            "verdict": verdict("supp_verdict_fatal_blackbox"),
            "dimensions": [signals["d1"], signals["d2"], signals["d3"]],
            "fatal_reason": "blackbox", "skip_reason": None,
            "signals": signals,
        }
    return None


def _supplier_missing(signals: dict[str, Any]) -> bool:
    """数据不足检查：身份 + 年限 ≥ 2 项缺失 → 跳过。"""
    return (0 if signals["has_id"] else 1) + (0 if signals["has_years"] else 1) >= 2


# ====================================================================
# 信号强度计数 + 档位匹配（6 规则）
# ====================================================================

def _supplier_tier(signals: dict[str, Any]) -> str:
    """身份硬门槛 + 强-弱净分 → 档位。

    拨正后：身份弱（贸易商）一票警惕，不管认证年限多好；
    强/中/弱都计入，弱信号不再被「强=1 或 中≥2」吞掉。
    """
    identity: str = signals["identity_strength"]
    cert: str = signals["cert_strength"]
    years: str = signals["years_strength"]

    # 身份硬门槛：贸易商赚差价、品控不可控，一票警惕
    if identity == "weak":
        return "caution_weak2"

    strong = medium = weak = 0
    for s in (identity, cert, years):
        if s == "strong":
            strong += 1
        elif s == "medium":
            medium += 1
        elif s == "weak":
            weak += 1

    # 真工厂 + 深度验厂 → 信任
    if identity == "strong" and cert == "strong":
        return "trust_strong2"
    # 强-弱净分 ≥ 1 → 还行（弱信号已计入，不再漏）
    if strong - weak >= 1:
        return "usable_ok"
    return "caution_weak2"


# ====================================================================
# verdict 组装
# ====================================================================

def _supplierverdict(tier: str, signals: dict[str, Any]) -> dict[str, Any]:
    """根据 tier 组装供应商 verdict dict。"""
    shop_years = signals["shop_years"]
    cert_type = signals["cert_type"]
    # 提取纯认证名："深度认证·sgs" → "SGS"；"第三方验厂" → "第三方验厂"
    if "·" in cert_type:
        cert_name = cert_type.rsplit("·", 1)[-1]
    else:
        cert_name = cert_type
    cert_display = cert_name.upper() if cert_name.isascii() else cert_name
    years_str = str(shop_years) if shop_years is not None else ""

    # 收集好/坏信号 glossary key
    good_keys: list[str] = []
    bad_keys: list[str] = []

    for field in ("identity", "cert", "years"):
        label = signals[f"{field}_label"]
        strength = signals[f"{field}_strength"]
        if not label:
            continue
        if strength in ("strong", "medium"):
            good_keys.append(label)
        elif strength == "weak":
            bad_keys.append(label)

    # 动作建议
    has_bad_cert = signals["cert_strength"] in ("weak",) and signals["has_cert"]
    has_bad_id = signals["identity_strength"] == "weak"
    has_bad_years = signals["years_strength"] == "weak"

    if has_bad_id and has_bad_cert:
        action_key = "supp_action_compare_inspect"
    elif has_bad_id:
        action_key = "supp_action_compare"
    elif has_bad_cert:
        action_key = "supp_action_inspect"
    elif has_bad_years:
        action_key = "supp_action_check_delivery"
    else:
        action_key = "supp_action_ok"

    # tier → (verdict_key, summary_key, grade)
    if tier == "skip":
        missing = (0 if signals["has_id"] else 1) + (0 if signals["has_years"] else 1)
        v = verdict("supp_verdict_skip_nodata", missing_count=str(missing))
        summary_kv, grade = verdict("supp_summary_skip"), "none"
    elif tier == "fatal_blackbox":
        v, summary_kv, grade = verdict("supp_verdict_fatal_blackbox"), verdict("supp_summary_fatal"), "bad"
    elif tier == "trust_strong2":
        v = verdict("supp_verdict_trust_strong2",
                     good_part_keys=good_keys, years=years_str, cert_text=cert_display)
        summary_kv, grade = verdict("supp_summary_trust"), "go"
    elif tier == "usable_ok":
        # bad_parts 空时用不带「但」的模板，避免拼出「但。」残句
        v_key = "supp_verdict_usable_ok" if bad_keys else "supp_verdict_usable_ok_nobad"
        v = verdict(v_key,
                     good_part_keys=good_keys, bad_part_keys=bad_keys,
                     years=years_str, cert_text=cert_type, action_key=action_key)
        summary_kv, grade = verdict("supp_summary_usable"), "ok"
    else:  # caution_weak2
        v = verdict("supp_verdict_caution_weak2",
                     bad_part_keys=bad_keys, good_part_keys=good_keys,
                     years=years_str, cert_text=cert_type, action_key=action_key)
        summary_kv, grade = verdict("supp_summary_caution"), "bad"

    total = sum(signals[d]["score"] for d in ("d1", "d2", "d3"))

    return {
        "score": total, "max_score": 9,
        "grade": grade, "tier": tier,
        "summary": summary_kv, "verdict": v,
        "dimensions": [signals["d1"], signals["d2"], signals["d3"]],
        "fatal_reason": "blackbox" if tier == "fatal_blackbox" else None,
        "skip_reason": "missing_data" if tier == "skip" else None,
        "signals": signals,
    }


# ====================================================================
# 公开入口
# ====================================================================

def evaluate_supplier(mapped: dict[str, Any]) -> dict[str, Any]:
    """供应商维度评判：3 维信号强度 → 黑箱检查 → 数据检查 → 6 规则信号计数 → 判词。"""
    signals = _supplier_signals(mapped)
    fatal = _supplier_fatal(signals)
    if fatal is not None:
        return fatal
    if _supplier_missing(signals):
        return _supplierverdict("skip", signals)
    return _supplierverdict(_supplier_tier(signals), signals)
