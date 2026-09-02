"""产品评判引擎 — 4 维信号（销量/关注/门槛/退货）→ 加权评分 → 规则档位匹配 → 判词。

纯函数模块，零外部依赖。被 evaluator.py 导入，外部代码不应直接引用此文件。

依据：docs/技术-评分标准与标签体系.md §一
"""
from typing import Any, cast

from domain.evaluate._base import (
    verdict, safe_int, safe_float,
    SOLD_HOT, SOLD_POTENTIAL,
    PRICE_LOW, PRICE_MID, MOQ_LOW, MOQ_MID,
    WANTED_HIGH, WANTED_MID,
)

# 产品维度权重（核心算法，权威源：docs/技术-评分标准与标签体系.md §一）
# 产品 4 维：销量 d1 / 关注 d5 / 门槛 d3 / 退货 d6。键名保留 v1 空洞编号不重排。
# 加权总分 = Σ(强度分 × 权重)，满分 3.0。权重只做展示分，档位仍由规则判定。
PROD_DIM_WEIGHTS: dict[str, float] = {"d1": 0.35, "d5": 0.25, "d3": 0.25, "d6": 0.15}
PROD_ACTIVE_DIMS: tuple[str, ...] = ("d1", "d5", "d3", "d6")  # 展示顺序：销量→关注→门槛→退货


# ====================================================================
# 信号提取
# ====================================================================

def _product_signals(mapped: dict[str, Any]) -> dict[str, Any]:
    """从 mapped dict 提取 4 维信号 + 评分 + 标签。

    v2：产品只读产品级数据（销量/门槛/关注/退货）。复购率、好评率是店铺级数据，
    已归供应商评分（_supplier），产品侧不消费 mapped.repurchase / positive_rate。

    Returns:
        {sold, price, moq, wanted, return7day, has_service_labels, unit,
         d1/d3/d5/d6 每个维度的 {score, label_key, data_fmt/data_key, data_num/data_params, ref_fmt, ref_num}}
    """
    price_cny_raw: Any = mapped.get("priceCNY")
    price_cny: dict[str, Any] = cast(dict[str, Any], price_cny_raw) if isinstance(price_cny_raw, dict) else {}
    price: float | None = safe_float(price_cny.get("low"))
    entry_price: float | None = safe_float(price_cny.get("high")) or price
    moq: int | None = safe_int(mapped.get("moq"))
    sales: int | None = safe_int(mapped.get("sold"))
    wanted: int | None = safe_int(mapped.get("wantBuy"))
    return7day: str = str(mapped.get("return7day", ""))
    has_service_labels: bool = bool(mapped.get("has_service_labels"))
    unit: str = str(mapped.get("unit", ""))

    display_price: float = entry_price if entry_price is not None else (price or 0)

    signals: dict[str, Any] = {
        "sold": sales, "price": price, "moq": moq,
        "wanted": wanted, "return7day": return7day,
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

    # (D2 复购已移除 — 店铺级数据归供应商评分，见 _supplier.py 权重表)

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

    # (D4 好评已移除 — 店铺级数据归供应商评分，见 _supplier.py 权重表)

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

def _product_missing(signals: dict[str, Any]) -> bool:
    """核心数据缺失检查：销量 + 退货 ≥ 2 项缺失 → 跳过（v2 无复购维度）。"""
    missing = 0
    if signals["sold"] is None:
        missing += 1
    if not signals["has_service_labels"]:
        missing += 1
    return missing >= 2


# ====================================================================
# 档位匹配（12 规则，顺序敏感）
# ====================================================================

def _product_tier(signals: dict[str, Any]) -> str:
    """产品规则按优先级顺序匹配，返回 tier key（v2：无复购/好评依赖）。

    产品只剩真实产品信号：销量 / 关注 / 门槛 / 退货。
    档位语义：go 双热（热销+高关注）；trial 热销单信号/高关注低销量/多中等；
    watch 信号平平。产品无 caution/bad（低质信号不足 → 观望，不轻判「坏品」）。
    无复购数据后 go 档变严是特性——判词向用户传递「新品默认更谨慎」。
    """
    sold: int | None = signals["sold"]
    wanted: int | None = signals["wanted"]

    medium = _count_medium(signals)

    # Rule 1: 热销 + 高关注（双热信号 → go）
    if (sold is not None and sold > SOLD_HOT
            and wanted is not None and wanted > WANTED_HIGH):
        return "go_hot_wanted"
    # Rule 2: 热销但关注不高 → 试（单一信号撑不起 go）
    if (sold is not None and sold > SOLD_HOT
            and (wanted is None or wanted <= WANTED_HIGH)):
        return "trial_hot_unknown"
    # Rule 3: 高关注 + 低销量 → 试（需求未兑现，先小单）
    if (wanted is not None and wanted > WANTED_HIGH
            and (sold is None or sold <= SOLD_POTENTIAL)):
        return "trial_wanted_low"
    # Rule 4: 中等亮点 ≥ 3 → 试
    if medium >= 3:
        return "trial_medium3"
    # Rule 5: 中等亮点 1-2 → 观望
    if medium >= 1:
        return "watch_medium12"
    # Rule 6: 全维度平平 / 新品无销量 → 观望
    return "watch_flat"


def _count_medium(signals: dict[str, Any]) -> int:
    """统计活跃维度（d1/d3/d5/d6）score == 2 的数量。"""
    return sum(1 for d in PROD_ACTIVE_DIMS if signals[d]["score"] == 2)


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
    sold: int | None = signals["sold"]
    wanted: int | None = signals["wanted"]
    medium = _count_medium(signals)

    base = _common_params(signals)

    # tier → (verdict_key, summary_key, grade, extra_params)
    # v2 产品无复购/好评依赖 tier（go_repurchase/go_hot_repeat/trial_rep_low/caution_* 已删）
    mapping: dict[str, tuple[str, str, str, dict[str, Any]]] = {
        "skip":            ("prod_verdict_skip_nodata",    "prod_summary_watch",   "none", {"missing_count": str(_count_missing(signals))}),
        "go_hot_wanted":   ("prod_verdict_go_hot_wanted",  "prod_summary_go",      "go",   {"sold": str(sold or 0), "wanted": str(wanted or 0)}),
        "trial_hot_unknown": ("prod_verdict_trial_hot_unknown", "prod_summary_trial", "ok", {"sold": str(sold or 0)}),
        "trial_wanted_low":  ("prod_verdict_trial_wanted_low",  "prod_summary_trial", "ok", {"wanted": str(wanted or 0), "sold": str(sold or 0)}),
        "trial_medium3":   ("prod_verdict_trial_medium3",  "prod_summary_trial",   "ok",   {"highlight_count": str(medium)}),
        "watch_medium12":  ("prod_verdict_watch_medium12", "prod_summary_watch",   "none", {"highlight_count": str(medium)}),
        "watch_flat":      ("prod_verdict_watch_flat",     "prod_summary_watch",   "none", {}),
    }

    v_key, s_key, grade, extra = mapping.get(tier, ("prod_verdict_watch_flat", "prod_summary_watch", "none", {}))
    v = verdict(v_key, **extra, **base)
    summary_kv = verdict(s_key)

    # 加权总分（展示分，满分 3.0）：Σ(强度分 × 权重)。档位仍由规则判定。
    total_score = round(sum(signals[d]["score"] * PROD_DIM_WEIGHTS[d] for d in PROD_ACTIVE_DIMS), 2)

    return _make_result(total_score, grade, tier, summary_kv, v, signals,
                        skip_reason="missing_data" if tier == "skip" else None)


def _count_missing(signals: dict[str, Any]) -> int:
    """统计核心数据缺失项数（v2：销量 + 退货）。"""
    return (1 if signals["sold"] is None else 0) + \
           (1 if not signals["has_service_labels"] else 0)


def _make_result(score: float, grade: str, tier: str,
                 summary: dict[str, Any], verdict: dict[str, Any],
                 signals: dict[str, Any],
                 fatal_reason: str | None = None,
                 skip_reason: str | None = None) -> dict[str, Any]:
    """组装统一的 result dict。"""
    # 维度展示顺序：销量 → 关注 → 门槛 → 退货（PROD_ACTIVE_DIMS）
    dims = [signals[d] for d in PROD_ACTIVE_DIMS]
    return {
        "score": score, "max_score": 3.0,
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
    """产品维度评判：4 维信号 → 数据检查 → 规则档位匹配 → 加权评分 + 判词。"""
    signals = _product_signals(mapped)
    if _product_missing(signals):
        return _productverdict("skip", signals)
    return _productverdict(_product_tier(signals), signals)
