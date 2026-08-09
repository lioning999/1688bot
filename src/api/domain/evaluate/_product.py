"""产品评判引擎 — 6 维信号 → 致命检查 → 12 规则档位匹配 → 判词。

纯函数模块，零外部依赖。被 evaluator.py 导入，外部代码不应直接引用此文件。

依据：docs/技术-评分标准与标签体系.md §一
"""
from typing import Any, cast

from domain.evaluate._base import (
    verdict, safe_int, safe_float,
    SOLD_HOT, SOLD_POTENTIAL,
    REPURCHASE_HIGH, REPURCHASE_MID,
    PRICE_LOW, PRICE_MID, MOQ_LOW, MOQ_MID,
    POSITIVE_HIGH, POSITIVE_MID, POSITIVE_BAD,
    WANTED_HIGH, WANTED_MID,
)


# ====================================================================
# 信号提取
# ====================================================================

def _product_signals(mapped: dict[str, Any]) -> dict[str, Any]:
    """从 mapped dict 提取 6 维信号 + 评分 + 标签。

    Returns:
        {sold, repurchase, price, moq, positive, wanted, return7day, has_service_labels, unit,
         d1~d6 每个维度的 {score, label_key, data_fmt/data_key, data_num/data_params, ref_fmt, ref_num}}
    """
    price_cny_raw: Any = mapped.get("priceCNY")
    price_cny: dict[str, Any] = cast(dict[str, Any], price_cny_raw) if isinstance(price_cny_raw, dict) else {}
    price: float | None = safe_float(price_cny.get("low"))
    entry_price: float | None = safe_float(price_cny.get("high")) or price
    moq: int | None = safe_int(mapped.get("moq"))
    sales: int | None = safe_int(mapped.get("sold"))
    repurchase: float | None = safe_float(mapped.get("repurchase"))
    positive: float | None = safe_float(mapped.get("positive_rate"))
    wanted: int | None = safe_int(mapped.get("wantBuy"))
    return7day: str = str(mapped.get("return7day", ""))
    has_service_labels: bool = bool(mapped.get("has_service_labels"))
    unit: str = str(mapped.get("unit", ""))

    display_price: float = entry_price if entry_price is not None else (price or 0)

    signals: dict[str, Any] = {
        "sold": sales, "repurchase": repurchase, "price": price, "moq": moq,
        "positive": positive, "wanted": wanted, "return7day": return7day,
        "has_service_labels": has_service_labels, "unit": unit,
        "display_price": display_price,
    }

    # D1 销量
    if sales is None:
        signals["d1"] = _dim("d1", 0, "🔥", "prod_dim_d1_name", "",
                             data_fmt="", data_num=None, ref_fmt="", ref_num=None)
    elif sales > SOLD_HOT:
        signals["d1"] = _dim("d1", 3, "🔥", "prod_dim_d1_name_high", "prod_dim_d1_label",
                             "prod_dim_d1_data_fmt", sales, "prod_dim_d1_ref_fmt", SOLD_HOT)
    elif sales > SOLD_POTENTIAL:
        signals["d1"] = _dim("d1", 2, "🔥", "prod_dim_d1_name", "",
                             "prod_dim_d1_data_fmt", sales, "prod_dim_d1_ref_fmt", SOLD_HOT)
    else:
        signals["d1"] = _dim("d1", 1, "🔥", "prod_dim_d1_name", "",
                             "prod_dim_d1_data_fmt", sales, "prod_dim_d1_ref_fmt", SOLD_HOT)

    # D2 复购
    if repurchase is None:
        signals["d2"] = _dim("d2", 0, "🔄", "prod_dim_d2_name", "",
                             data_fmt="", data_num=None, ref_fmt="", ref_num=None)
    elif repurchase > REPURCHASE_HIGH:
        signals["d2"] = _dim("d2", 3, "🔄", "prod_dim_d2_name_high", "prod_dim_d2_label",
                             "prod_dim_d2_data_fmt", repurchase, "prod_dim_d2_ref_fmt", REPURCHASE_HIGH)
    elif repurchase > REPURCHASE_MID:
        signals["d2"] = _dim("d2", 2, "🔄", "prod_dim_d2_name", "",
                             "prod_dim_d2_data_fmt", repurchase, "prod_dim_d2_ref_fmt", REPURCHASE_HIGH)
    else:
        signals["d2"] = _dim("d2", 1, "🔄", "prod_dim_d2_name", "",
                             "prod_dim_d2_data_fmt", repurchase, "prod_dim_d2_ref_fmt", REPURCHASE_HIGH)

    # D3 门槛
    if price is None or moq is None:
        signals["d3"] = _dim_p("d3", 0, "💰", "prod_dim_d3_name", "",
                               data_fmt="", data_params={}, ref_fmt="", ref_params={})
    elif price < PRICE_LOW and moq <= MOQ_LOW:
        signals["d3"] = _dim_p("d3", 3, "💰", "prod_dim_d3_name_high", "prod_dim_d3_label",
                               "prod_dim_d3_data_fmt", {"price": display_price, "moq": moq, "unit": unit})
    elif price < PRICE_MID and moq <= MOQ_MID:
        signals["d3"] = _dim_p("d3", 2, "💰", "prod_dim_d3_name", "",
                               "prod_dim_d3_data_fmt", {"price": display_price, "moq": moq, "unit": unit})
    else:
        signals["d3"] = _dim_p("d3", 1, "💰", "prod_dim_d3_name_low", "",
                               "prod_dim_d3_data_fmt", {"price": display_price, "moq": moq, "unit": unit})

    # D4 口碑
    if positive is None:
        signals["d4"] = _dim("d4", 0, "⭐", "prod_dim_d4_name", "",
                             data_fmt="", data_num=None, ref_fmt="", ref_num=None)
    elif positive >= POSITIVE_HIGH:
        signals["d4"] = _dim("d4", 3, "⭐", "prod_dim_d4_name_high", "prod_dim_d4_label",
                             "prod_dim_d4_data_fmt", positive, "prod_dim_d4_ref_fmt", POSITIVE_HIGH)
    elif positive >= POSITIVE_MID:
        signals["d4"] = _dim("d4", 2, "⭐", "prod_dim_d4_name", "",
                             "prod_dim_d4_data_fmt", positive, "prod_dim_d4_ref_fmt", POSITIVE_HIGH)
    else:
        signals["d4"] = _dim("d4", 1, "⭐", "prod_dim_d4_name", "",
                             "prod_dim_d4_data_fmt", positive, "prod_dim_d4_ref_fmt", POSITIVE_HIGH)

    # D5 关注（wantBuy）
    if wanted is None:
        signals["d5"] = _dim("d5", 0, "👀", "prod_dim_d5_name", "",
                             data_fmt="", data_num=None, ref_fmt="", ref_num=None)
    elif wanted > WANTED_HIGH:
        signals["d5"] = _dim("d5", 3, "👀", "prod_dim_d5_name_high", "prod_dim_d5_label",
                             "prod_dim_d5_data_fmt", wanted, "prod_dim_d5_ref_fmt", WANTED_HIGH)
    elif wanted > WANTED_MID:
        signals["d5"] = _dim("d5", 2, "👀", "prod_dim_d5_name", "",
                             "prod_dim_d5_data_fmt", wanted, "prod_dim_d5_ref_fmt", WANTED_HIGH)
    else:
        signals["d5"] = _dim("d5", 1, "👀", "prod_dim_d5_name_low", "",
                             "prod_dim_d5_data_fmt", wanted, "prod_dim_d5_ref_fmt", WANTED_HIGH)

    # D6 退货
    if not has_service_labels:
        signals["d6"] = {"key": "d6", "score": 0, "icon": "🛡️",
                         "name_key": "prod_dim_d6_name", "label_key": "",
                         "data_key": "", "ref_fmt": "", "ref_params": {}}
    elif return7day == "OK":
        signals["d6"] = {"key": "d6", "score": 3, "icon": "🛡️",
                         "name_key": "prod_dim_d6_name_high", "label_key": "prod_dim_d6_label",
                         "data_key": "prod_dim_d6_data_ok", "ref_fmt": "", "ref_params": {}}
    else:
        signals["d6"] = {"key": "d6", "score": 1, "icon": "🛡️",
                         "name_key": "prod_dim_d6_name", "label_key": "",
                         "data_key": "prod_dim_d6_data_no", "ref_fmt": "", "ref_params": {}}

    # 风险标记：无7天退货 → 不否决，但判词需提醒
    signals["risk_flag"] = "no_return" if (has_service_labels and return7day != "OK") else None

    return signals


def _dim(key: str, score: int, icon: str, name_key: str, label_key: str,
         data_fmt: str, data_num: int | float | None,
         ref_fmt: str = "", ref_num: int | float | None = None) -> dict[str, Any]:
    """构建数值型维度 dict（D1/D2/D4/D5）。"""
    return {"key": key, "score": score, "icon": icon,
            "name_key": name_key, "label_key": label_key,
            "data_fmt": data_fmt, "data_num": data_num,
            "ref_fmt": ref_fmt, "ref_num": ref_num}


def _dim_p(key: str, score: int, icon: str, name_key: str, label_key: str,
           data_fmt: str, data_params: dict[str, Any],
           ref_fmt: str = "", ref_params: dict[str, Any] | None = None) -> dict[str, Any]:
    """构建多参数维度 dict（D3 门槛）。"""
    return {"key": key, "score": score, "icon": icon,
            "name_key": name_key, "label_key": label_key,
            "data_fmt": data_fmt, "data_params": data_params,
            "ref_fmt": ref_fmt, "ref_params": ref_params or {}}


# ====================================================================
# 致命短板 + 数据不足
# ====================================================================

def _product_fatal(signals: dict[str, Any]) -> dict[str, Any] | None:
    """致命短板一票否决。

    - 好评率 < 80%（接口保留，当前数据覆盖率 0%）

    无7天退货不再一票否决——改为 D6=1 低分 + risk_flag 标风险，
    由12规则正常匹配 tier，判词模板追加退货风险提醒。
    """
    if signals["positive"] is not None and signals["positive"] < POSITIVE_BAD:
        return _make_result(0, "bad", "fatal_badrate",
                            verdict("prod_summary_fatal"),
                            verdict("prodverdict_fatal_badrate",
                                     positive=str(signals["positive"])),
                            signals, fatal_reason="badrate")
    return None


def _product_missing(signals: dict[str, Any]) -> bool:
    """核心数据缺失检查：销量 + 复购 + 退货 ≥ 2 项缺失 → 跳过。"""
    missing = 0
    if signals["sold"] is None:
        missing += 1
    if signals["repurchase"] is None:
        missing += 1
    if not signals["has_service_labels"]:
        missing += 1
    return missing >= 2


# ====================================================================
# 档位匹配（12 规则，顺序敏感）
# ====================================================================

def _product_tier(signals: dict[str, Any]) -> str:
    """12 条规则按优先级顺序匹配，返回 tier key。

    前置条件：已通过 fatal 和 missing 检查。
    中等亮点 = score == 2 的维度数（score=3 由规则 3-9 覆盖）。
    """
    sold: int | None = signals["sold"]
    repurchase: float | None = signals["repurchase"]
    wanted: int | None = signals["wanted"]

    medium = _count_medium(signals)

    # Rule 3: 高复购 + 有销量基础
    if (repurchase is not None and repurchase > REPURCHASE_HIGH
            and sold is not None and sold > SOLD_POTENTIAL):
        return "go_repurchase"
    # Rule 4: 热销 + 高关注（双热信号）
    if (sold is not None and sold > SOLD_HOT
            and wanted is not None and wanted > WANTED_HIGH):
        return "go_hot_wanted"
    # Rule 5: 热销 + 有复购
    if (sold is not None and sold > SOLD_HOT
            and repurchase is not None and repurchase > REPURCHASE_MID):
        return "go_hot_repeat"
    # Rule 6: 热销 + 复购未知 + 关注不高
    if (sold is not None and sold > SOLD_HOT
            and repurchase is None
            and (wanted is None or wanted <= WANTED_HIGH)):
        return "trial_hot_unknown"
    # Rule 7: 热销 + 已知低复购
    if (sold is not None and sold > SOLD_HOT
            and repurchase is not None and repurchase <= REPURCHASE_MID):
        return "caution_hot_low"
    # Rule 8: 高关注 + 低销量
    if (wanted is not None and wanted > WANTED_HIGH
            and (sold is None or sold <= SOLD_POTENTIAL)):
        return "trial_wanted_low"
    # Rule 9: 高复购 + 销量少（按门槛拆两档）
    if (repurchase is not None and repurchase > REPURCHASE_HIGH
            and (sold is None or sold <= SOLD_POTENTIAL)):
        if signals["d3"]["score"] >= 2:
            return "trial_rep_low"     # 门槛低 → 值得试
        return "caution_rep_low"       # 门槛高 → 先算账
    # Rule 10: 中等亮点 ≥ 3
    if medium >= 3:
        return "trial_medium3"
    # Rule 11: 中等亮点 1-2
    if medium >= 1:
        return "watch_medium12"
    # Rule 12: 全维度平平 / 新品无销量
    return "watch_flat"


def _count_medium(signals: dict[str, Any]) -> int:
    """统计 score == 2 的维度数。"""
    return sum(1 for d in ("d1", "d2", "d3", "d4", "d5", "d6")
               if signals[d]["score"] == 2)


# ====================================================================
# verdict 组装
# ====================================================================

def _barrier_tip_key(signals: dict[str, Any]) -> str:
    """根据门槛维度得分返回门槛附言 glossary key。"""
    score = signals["d3"]["score"]
    if score == 3:
        return "prod_barrier_tip_low"
    elif score == 2:
        return "prod_barrier_tip_mid"
    return "prod_barrier_tip_high"


def _common_params(signals: dict[str, Any]) -> dict[str, Any]:
    """提取 verdict 模板通用参数。"""
    params: dict[str, Any] = {"barrier_tip_key": _barrier_tip_key(signals)}
    if signals["display_price"] is not None:
        params["price"] = f"{signals['display_price']:.2f}"
    if signals["moq"] is not None:
        params["moq"] = str(signals["moq"])
    if signals.get("unit"):
        params["unit"] = signals["unit"]
    if signals.get("risk_flag"):
        params["risk_note_key"] = "prod_risk_note_no_return"
    return params


def _productverdict(tier: str, signals: dict[str, Any]) -> dict[str, Any]:
    """根据 tier 组装完整 verdict dict。"""
    sold = signals["sold"]
    repurchase = signals["repurchase"]
    wanted = signals["wanted"]
    medium = _count_medium(signals)

    base = _common_params(signals)

    # tier → (verdict_key, summary_key, grade, extra_params)
    mapping: dict[str, tuple[str, str, str, dict[str, Any]]] = {
        "skip":            ("prodverdict_skip_nodata",    "prod_summary_watch",   "none", {"missing_count": str(_count_missing(signals))}),
        "go_repurchase":   ("prodverdict_go_repurchase",  "prod_summary_go",      "go",   {"sold": str(sold or 0), "repurchase": str(repurchase or 0)}),
        "go_hot_wanted":   ("prodverdict_go_hot_wanted",  "prod_summary_go",      "go",   {"sold": str(sold or 0), "wanted": str(wanted or 0)}),
        "go_hot_repeat":   ("prodverdict_go_hot_repeat",  "prod_summary_go",      "go",   {"sold": str(sold or 0), "repurchase": str(repurchase or 0)}),
        "trial_hot_unknown": ("prodverdict_trial_hot_unknown", "prod_summary_trial", "ok", {"sold": str(sold or 0)}),
        "trial_wanted_low":  ("prodverdict_trial_wanted_low",  "prod_summary_trial", "ok", {"wanted": str(wanted or 0), "sold": str(sold or 0)}),
        "trial_rep_low":   ("prodverdict_trial_rep_low",  "prod_summary_trial",   "ok",   {"repurchase": str(repurchase or 0), "sold": str(sold or 0)}),
        "trial_medium3":   ("prodverdict_trial_medium3",  "prod_summary_trial",   "ok",   {"highlight_count": str(medium)}),
        "caution_hot_low": ("prodverdict_caution_hot_low","prod_summary_caution",  "bad",  {"sold": str(sold or 0), "repurchase": str(repurchase or 0)}),
        "caution_rep_low": ("prodverdict_caution_rep_low","prod_summary_caution",  "bad",  {"repurchase": str(repurchase or 0), "sold": str(sold or 0)}),
        "watch_medium12":  ("prodverdict_watch_medium12", "prod_summary_watch",   "none", {"highlight_count": str(medium)}),
        "watch_flat":      ("prodverdict_watch_flat",     "prod_summary_watch",   "none", {}),
    }

    v_key, s_key, grade, extra = mapping.get(tier, ("prodverdict_watch_flat", "prod_summary_watch", "none", {}))
    v = verdict(v_key, **extra, **base)
    summary_kv = verdict(s_key)

    total = sum(signals[d]["score"] for d in ("d1", "d2", "d3", "d4", "d5", "d6"))

    return _make_result(total, grade, tier, summary_kv, v, signals,
                        skip_reason="missing_data" if tier == "skip" else None)


def _count_missing(signals: dict[str, Any]) -> int:
    """统计核心数据缺失项数。"""
    return (1 if signals["sold"] is None else 0) + \
           (1 if signals["repurchase"] is None else 0) + \
           (1 if not signals["has_service_labels"] else 0)


def _make_result(score: int, grade: str, tier: str,
                 summary: dict[str, Any], verdict: dict[str, Any],
                 signals: dict[str, Any],
                 fatal_reason: str | None = None,
                 skip_reason: str | None = None) -> dict[str, Any]:
    """组装统一的 result dict。"""
    dims = [signals["d1"], signals["d2"], signals["d3"],
            signals["d4"], signals["d5"], signals["d6"]]
    return {
        "score": score, "max_score": 18,
        "grade": grade, "tier": tier,
        "summary": summary, "verdict": verdict,
        "dimensions": dims,
        "fatal_reason": fatal_reason,
        "skip_reason": skip_reason,
        "signals": signals,
    }


# ====================================================================
# 公开入口
# ====================================================================

def evaluate_product(mapped: dict[str, Any]) -> dict[str, Any]:
    """产品维度评判：6 维信号 → 致命检查 → 数据检查 → 12 规则档位匹配 → 判词。"""
    signals = _product_signals(mapped)
    fatal = _product_fatal(signals)
    if fatal is not None:
        return fatal
    if _product_missing(signals):
        return _productverdict("skip", signals)
    return _productverdict(_product_tier(signals), signals)
