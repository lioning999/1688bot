"""双维度评判引擎 — 产品 + 供应商 纯函数模块。

零外部依赖，零 IO，零随机。同一输入永远同一输出。
产品 6 字段 → 5 维度分档（D1销量/D2复购/D3门槛/D4口碑/D5退货）→ 0-15 总分 → 人话判词 KEY。
供应商 4 字段 → 3 维度分档 → 0-9 总分 → 等级 + 人话判词 KEY。

依据：docs/技术-货品维度评判标准.md + docs/技术-供应商维度评判标准.md
"""

from typing import Any


# ====================================================================
# 工具函数
# ====================================================================

def _verdict(key: str, **params: Any) -> dict[str, Any]:
    """构建判词输出：{key, params} dict。

    key 对应 term_glossary.json 中的条目，display_builder 负责查表 + 参数替换。
    """
    return {"key": key, "params": params}


def _safe_int(val: Any) -> int | None:
    """安全转 int。None / 非数字 → None。"""
    if val is None:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _safe_float(val: Any) -> float | None:
    """安全转 float。None / 非数字 → None。"""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ====================================================================
# 产品评判（市场验证）
# ====================================================================

def evaluate_product(mapped: dict[str, Any]) -> dict[str, Any]:
    """产品维度评判：销量 + 复购 + 门槛 + 口碑 + 退货 → 0-15 分。

    从 mapped dict 提取 6 个字段，5 维度分档，输出结构化评判结果。
    字段缺失 → 该维度 0 分，不影响其他维度。

    总分阈值：12-15 值得拿样 / 8-11 建议拿样 / 5-7 自己判断 / 2-4 先看看 / 0-1 数据不足
    """
    # ---- 提取字段 ----
    price_cny: dict[str, Any] = mapped.get("priceCNY") or {}
    price: float | None = _safe_float(price_cny.get("low")) if isinstance(price_cny, dict) else None
    moq: int | None = _safe_int(mapped.get("moq"))
    sales: int | None = _safe_int(mapped.get("sold"))
    repurchase: float | None = _safe_float(mapped.get("repurchase"))
    positive: float | None = _safe_float(mapped.get("positive_rate"))
    return7day: str = str(mapped.get("return7day", ""))
    has_service_labels: bool = bool(mapped.get("has_service_labels"))

    dims: dict[str, dict[str, Any]] = {}

    # ---- D1 销量（这个货卖得动吗？） ----
    if sales is None:
        dims["d1"] = {"key": "d1", "score": 0, "icon": "🔥",
                       "name_key": "prod_dim_d1_name", "label_key": "",
                       "data_fmt": "", "data_num": None,
                       "ref_fmt": "", "ref_num": None}
    elif sales > 1000:
        dims["d1"] = {"key": "d1", "score": 3, "icon": "🔥",
                       "name_key": "prod_dim_d1_name_high", "label_key": "prod_dim_d1_label",
                       "data_fmt": "prod_dim_d1_data_fmt", "data_num": sales,
                       "ref_fmt": "prod_dim_d1_ref_fmt", "ref_num": 1000}
    elif sales > 100:
        dims["d1"] = {"key": "d1", "score": 2, "icon": "🔥",
                       "name_key": "prod_dim_d1_name", "label_key": "",
                       "data_fmt": "prod_dim_d1_data_fmt", "data_num": sales,
                       "ref_fmt": "prod_dim_d1_ref_fmt", "ref_num": 1000}
    else:
        dims["d1"] = {"key": "d1", "score": 1, "icon": "🔥",
                       "name_key": "prod_dim_d1_name", "label_key": "",
                       "data_fmt": "prod_dim_d1_data_fmt", "data_num": sales,
                       "ref_fmt": "prod_dim_d1_ref_fmt", "ref_num": 1000}

    # ---- D2 复购（买过的人还会补货吗？） ----
    if repurchase is None:
        dims["d2"] = {"key": "d2", "score": 0, "icon": "🔄",
                       "name_key": "prod_dim_d2_name", "label_key": "",
                       "data_fmt": "", "data_num": None,
                       "ref_fmt": "", "ref_num": None}
    elif repurchase > 30:
        dims["d2"] = {"key": "d2", "score": 3, "icon": "🔄",
                       "name_key": "prod_dim_d2_name_high", "label_key": "prod_dim_d2_label",
                       "data_fmt": "prod_dim_d2_data_fmt", "data_num": repurchase,
                       "ref_fmt": "prod_dim_d2_ref_fmt", "ref_num": 30}
    elif repurchase > 10:
        dims["d2"] = {"key": "d2", "score": 2, "icon": "🔄",
                       "name_key": "prod_dim_d2_name", "label_key": "",
                       "data_fmt": "prod_dim_d2_data_fmt", "data_num": repurchase,
                       "ref_fmt": "prod_dim_d2_ref_fmt", "ref_num": 30}
    else:
        dims["d2"] = {"key": "d2", "score": 1, "icon": "🔄",
                       "name_key": "prod_dim_d2_name", "label_key": "",
                       "data_fmt": "prod_dim_d2_data_fmt", "data_num": repurchase,
                       "ref_fmt": "prod_dim_d2_ref_fmt", "ref_num": 30}

    # ---- D3 门槛（试错会不会亏很多？） ----
    unit: str = str(mapped.get("unit", ""))
    if price is None or moq is None:
        dims["d3"] = {"key": "d3", "score": 0, "icon": "💰",
                       "name_key": "prod_dim_d3_name", "label_key": "",
                       "data_fmt": "", "data_params": {},
                       "ref_fmt": "", "ref_params": {}}
    elif price < 20 and moq <= 10:
        dims["d3"] = {"key": "d3", "score": 3, "icon": "💰",
                       "name_key": "prod_dim_d3_name_high", "label_key": "prod_dim_d3_label",
                       "data_fmt": "prod_dim_d3_data_fmt",
                       "data_params": {"price": price, "moq": moq, "unit": unit},
                       "ref_fmt": "", "ref_params": {}}
    elif price < 50 and moq <= 100:
        dims["d3"] = {"key": "d3", "score": 2, "icon": "💰",
                       "name_key": "prod_dim_d3_name", "label_key": "",
                       "data_fmt": "prod_dim_d3_data_fmt",
                       "data_params": {"price": price, "moq": moq, "unit": unit},
                       "ref_fmt": "", "ref_params": {}}
    else:
        dims["d3"] = {"key": "d3", "score": 1, "icon": "💰",
                       "name_key": "prod_dim_d3_name_low", "label_key": "",
                       "data_fmt": "prod_dim_d3_data_fmt",
                       "data_params": {"price": price, "moq": moq, "unit": unit},
                       "ref_fmt": "", "ref_params": {}}

    # ---- D4 口碑（收货人满意吗？） ----
    if positive is None:
        dims["d4"] = {"key": "d4", "score": 0, "icon": "⭐",
                       "name_key": "prod_dim_d4_name", "label_key": "",
                       "data_fmt": "", "data_num": None,
                       "ref_fmt": "", "ref_num": None}
    elif positive >= 98:
        dims["d4"] = {"key": "d4", "score": 3, "icon": "⭐",
                       "name_key": "prod_dim_d4_name_high", "label_key": "prod_dim_d4_label",
                       "data_fmt": "prod_dim_d4_data_fmt", "data_num": positive,
                       "ref_fmt": "prod_dim_d4_ref_fmt", "ref_num": 98}
    elif positive >= 95:
        dims["d4"] = {"key": "d4", "score": 2, "icon": "⭐",
                       "name_key": "prod_dim_d4_name", "label_key": "",
                       "data_fmt": "prod_dim_d4_data_fmt", "data_num": positive,
                       "ref_fmt": "prod_dim_d4_ref_fmt", "ref_num": 98}
    else:
        dims["d4"] = {"key": "d4", "score": 1, "icon": "⭐",
                       "name_key": "prod_dim_d4_name", "label_key": "",
                       "data_fmt": "prod_dim_d4_data_fmt", "data_num": positive,
                       "ref_fmt": "prod_dim_d4_ref_fmt", "ref_num": 98}

    # ---- D5 退货（能退吗？） ----
    if not has_service_labels:
        dims["d5"] = {"key": "d5", "score": 0, "icon": "🛡️",
                       "name_key": "prod_dim_d5_name", "label_key": "",
                       "data_key": "", "ref_fmt": "", "ref_params": {}}
    elif return7day == "OK":
        dims["d5"] = {"key": "d5", "score": 3, "icon": "🛡️",
                       "name_key": "prod_dim_d5_name_high", "label_key": "prod_dim_d5_label",
                       "data_key": "prod_dim_d5_data_ok", "ref_fmt": "", "ref_params": {}}
    else:
        dims["d5"] = {"key": "d5", "score": 1, "icon": "🛡️",
                       "name_key": "prod_dim_d5_name", "label_key": "",
                       "data_key": "prod_dim_d5_data_no", "ref_fmt": "", "ref_params": {}}

    # ---- 总分 + 人话 KEY ----
    total: int = sum(d["score"] for d in dims.values())

    if total >= 12:
        human_key = "prod_verdict_high"
    elif total >= 8:
        human_key = "prod_verdict_good"
    elif total >= 5:
        human_key = "prod_verdict_mid"
    elif total >= 2:
        human_key = "prod_verdict_low"
    else:
        human_key = "prod_verdict_none"

    # ---- 组头摘要 ----
    green_count: int = sum(1 for d in dims.values() if d["score"] == 3)
    if green_count >= 4:
        summary_kv = _verdict("prod_summary_high", count=str(green_count))
    elif green_count >= 2:
        summary_kv = _verdict("prod_summary_mid", count=str(green_count))
    elif green_count == 1:
        summary_kv = _verdict("prod_summary_low")
    else:
        summary_kv = _verdict("prod_summary_none")

    return {
        "score": total,
        "max_score": 15,
        "grade": _score_grade(total, 15),
        "summary": summary_kv,
        "verdict": _verdict(human_key),
        "dimensions": [dims["d1"], dims["d2"], dims["d3"], dims["d4"], dims["d5"]],
    }


# ====================================================================
# 供应商评判（靠谱度）
# ====================================================================

def evaluate_supplier(mapped: dict[str, Any]) -> dict[str, Any]:
    """供应商维度评判：身份 + 认证 + 年限 → 0-9 分。

    从 mapped dict 提取 4 个字段，3 维度分档，输出结构化评判结果。

    grade_key 阈值：7-9 ✅可信 / 4-6 ⚠️可合作 / 1-3 🔴谨慎 / 0 ⬜数据不足

    验证用例（来自 docs/技术-供应商维度评判标准.md §七）：
      #1 实力工厂/tuv/4年 → 9分 ✅可信
      #2 生产厂家/无/8个月 → 4分 ⚠️可合作
      #3 超级工厂/深度验厂/6年 → 9分 ✅可信
      #4 贸易商/SGS/5年 → 7分 ✅可信
      #5 普通商家/无/2年 → 4分 ⚠️可合作
      #6 全空 → 0分 ⬜数据不足
    """
    # ---- 提取字段 ----
    flags: str = str(mapped.get("factoryFlags") or "")
    seller_type: str = str(mapped.get("sellerType") or "")
    cert_type_raw: Any = mapped.get("certType")
    cert_type: str = str(cert_type_raw) if cert_type_raw else ""
    shop_years: int | None = _safe_int(mapped.get("shop_years"))

    dims: dict[str, dict[str, Any]] = {}

    # ---- D1 身份（是不是工厂？） ----
    # 高级认证工厂：超级工厂 / 源头旗舰 / 实力工厂
    is_advanced: bool = (
        seller_type in ("super_factory", "flagship")
        or any(kw in flags for kw in ("超级工厂", "源头旗舰", "实力工厂"))
    )
    is_trader: bool = (
        "非生产厂家" in flags
        or seller_type in ("trader",)
    )
    is_factory: bool = (
        any(kw in flags for kw in ("生产厂家", "源头工厂", "工厂直供", "通品工厂"))
        and not is_trader
    )

    if not flags and not seller_type:
        dims["d1"] = {"key": "d1", "score": 0, "icon": "🏭",
                       "name_key": "supp_dim_d1_name", "label_key": "",
                       "data_key": "", "ref_fmt": "", "ref_params": {}}
    elif is_advanced:
        # 从 flags 中取最亮眼的身份标签 KEY
        if "超级工厂" in flags:
            identity_key = "超级工厂"
        elif "源头旗舰" in flags:
            identity_key = "源头旗舰"
        elif "实力工厂" in flags:
            identity_key = "实力工厂"
        else:
            identity_key = "实力商家"
        dims["d1"] = {"key": "d1", "score": 3, "icon": "🏭",
                       "name_key": "supp_dim_d1_name_adv", "label_key": "supp_dim_d1_label_adv",
                       "data_key": identity_key, "ref_fmt": "", "ref_params": {}}
    elif is_factory:
        dims["d1"] = {"key": "d1", "score": 2, "icon": "🏭",
                       "name_key": "supp_dim_d1_name_factory", "label_key": "supp_dim_d1_label_factory",
                       "data_key": "工厂直供", "ref_fmt": "", "ref_params": {}}
    elif is_trader:
        dims["d1"] = {"key": "d1", "score": 1, "icon": "⚠️",
                       "name_key": "supp_dim_d1_name_trader", "label_key": "supp_dim_d1_label_trader",
                       "data_key": "贸易商", "ref_fmt": "", "ref_params": {}}
    else:
        dims["d1"] = {"key": "d1", "score": 1, "icon": "⚠️",
                       "name_key": "supp_dim_d1_name_trader", "label_key": "supp_dim_d1_label_trader",
                       "data_key": "贸易商", "ref_fmt": "", "ref_params": {}}

    # ---- D2 认证（有没有人验过？） ----
    cert_lower: str = cert_type.lower()
    has_deep_cert: bool = any(kw in cert_lower for kw in
                              ("深度验厂", "深度认证", "sgs", "tuv"))
    has_basic_cert: bool = bool(cert_type) and not has_deep_cert
    _cert_in_glossary: bool = cert_type in ("深度验厂", "实地认证", "第三方验厂", "SGS 实地认证")

    if cert_type_raw is None:
        dims["d2"] = {"key": "d2", "score": 0, "icon": "📋",
                       "name_key": "supp_dim_d2_name", "label_key": "",
                       "data_key": "", "ref_fmt": "", "ref_params": {}}
    elif not cert_type:
        dims["d2"] = {"key": "d2", "score": 1, "icon": "📋",
                       "name_key": "supp_dim_d2_name", "label_key": "",
                       "data_key": "supp_dim_d2_data_no_cert", "ref_fmt": "", "ref_params": {}}
    elif has_deep_cert:
        # 已知中文认证类型 → glossary key；ASCII（SGS/TUV）→ 原样透传无需翻译
        d2_data_key: str = cert_type if _cert_in_glossary else ""
        d2_data_text: str = cert_type.upper() if (cert_type.isascii() and not _cert_in_glossary) else ""
        dims["d2"] = {"key": "d2", "score": 3, "icon": "📋",
                       "name_key": "supp_dim_d2_name_deep", "label_key": "supp_dim_d2_label_deep",
                       "data_key": d2_data_key, "data_text": d2_data_text,
                       "ref_fmt": "", "ref_params": {}}
    elif has_basic_cert:
        d2_data_key2: str = cert_type if _cert_in_glossary else ""
        d2_data_text2: str = cert_type if not _cert_in_glossary else ""
        dims["d2"] = {"key": "d2", "score": 2, "icon": "📋",
                       "name_key": "supp_dim_d2_name", "label_key": "",
                       "data_key": d2_data_key2, "data_text": d2_data_text2,
                       "ref_fmt": "", "ref_params": {}}
    else:
        dims["d2"] = {"key": "d2", "score": 1, "icon": "📋",
                       "name_key": "supp_dim_d2_name", "label_key": "",
                       "data_key": "supp_dim_d2_data_no_cert", "ref_fmt": "", "ref_params": {}}

    # ---- D3 年限（干了多久？） ----
    if shop_years is None:
        dims["d3"] = {"key": "d3", "score": 0, "icon": "📅",
                       "name_key": "supp_dim_d3_name", "label_key": "",
                       "data_fmt": "", "data_num": None,
                       "ref_fmt": "", "ref_num": None}
    elif shop_years >= 3:
        dims["d3"] = {"key": "d3", "score": 3, "icon": "📅",
                       "name_key": "supp_dim_d3_name_old", "label_key": "supp_dim_d3_label_old",
                       "data_fmt": "supp_dim_d3_data_fmt", "data_num": shop_years,
                       "ref_fmt": "supp_dim_d3_ref_fmt", "ref_num": 3}
    elif shop_years >= 1:
        dims["d3"] = {"key": "d3", "score": 2, "icon": "📅",
                       "name_key": "supp_dim_d3_name", "label_key": "",
                       "data_fmt": "supp_dim_d3_data_fmt", "data_num": shop_years,
                       "ref_fmt": "supp_dim_d3_ref_fmt", "ref_num": 3}
    else:
        dims["d3"] = {"key": "d3", "score": 1, "icon": "📅",
                       "name_key": "supp_dim_d3_name_new", "label_key": "supp_dim_d3_label_new",
                       "data_key": "supp_dim_d3_data_short",
                       "ref_fmt": "supp_dim_d3_ref_fmt", "ref_num": 3}

    # ---- 总分 + 等级 ----
    total: int = sum(d["score"] for d in dims.values())

    if total >= 7:
        grade_key = "supplier_grade_verified"
        grade_css = "go"
    elif total >= 4:
        grade_key = "supplier_grade_ok"
        grade_css = "ok"
    elif total >= 1:
        grade_key = "supplier_grade_caution"
        grade_css = "bad"
    else:
        grade_key = "supplier_grade_unknown"
        grade_css = "none"

    # ---- 人话 KEY + 参数 ----
    human_key, human_params = _select_supplier_human(
        d1_score=dims["d1"]["score"],
        d2_score=dims["d2"]["score"],
        d3_score=dims["d3"]["score"],
        shop_years=shop_years,
        cert_type=cert_type,
        has_deep_cert=has_deep_cert,
        has_basic_cert=has_basic_cert,
    )

    # ---- 组头摘要 ----
    d1_name_key: str = str(dims["d1"].get("name_key", ""))
    d1_score_for_summary: int = dims["d1"]["score"]
    d3_score: int = dims["d3"]["score"]

    if d1_score_for_summary > 0 and d3_score >= 2 and shop_years:
        summary_kv = _verdict("supp_summary_both", identity_key=d1_name_key, years=str(shop_years))
    elif d1_score_for_summary > 0:
        summary_kv = _verdict("supp_summary_identity", identity_key=d1_name_key)
    elif d3_score >= 2 and shop_years:
        summary_kv = _verdict("supp_summary_years", years=str(shop_years))
    else:
        summary_kv = _verdict("supp_summary_none")

    return {
        "score": total,
        "max_score": 9,
        "grade": grade_css,
        "grade_key": grade_key,
        "summary": summary_kv,
        "verdict": _verdict(human_key, **human_params),
        "dimensions": [dims["d1"], dims["d2"], dims["d3"]],
    }


# ====================================================================
# 供应商人话模板选择
# ====================================================================

def _select_supplier_human(
    d1_score: int,
    d2_score: int,
    d3_score: int,
    shop_years: int | None,
    cert_type: str,
    has_deep_cert: bool,
    has_basic_cert: bool,
) -> tuple[str, dict[str, Any]]:
    """按身份驱动选择人话模板 KEY 并计算参数。

    8 条模板（T1-T8）+ 兜底（T0），详见 docs/技术-供应商维度评判标准.md §五。
    使用 score 判断身份，不再比对中文 label 文本。
    """
    is_old: bool = d3_score == 3       # ≥3年
    is_not_old: bool = d3_score <= 2    # <3年（含缺失）
    has_any_cert: bool = d2_score >= 2
    years: int = shop_years or 0

    # ---- 计算通用参数（glossary key，由 display_builder 查表翻译） ----
    # desc_key：年限描述 key（含 {n} 占位符的用 supp_desc_yrs_plus / supp_desc_yrs）
    if years >= 3:
        desc_key = "supp_desc_yrs_plus"
    elif years >= 1:
        desc_key = "supp_desc_yrs"
    elif years > 0:
        desc_key = "supp_desc_lt1"
    else:
        desc_key = "supp_desc_unknown"

    # reason_keys：不足之处的说明（list of glossary keys）
    reason_keys: list[str] = []
    if is_not_old and years and years < 3:
        reason_keys.append("supp_reason_short")
    if d2_score <= 1:
        reason_keys.append("supp_reason_no_cert")

    # cert_key：认证类型 key
    if has_deep_cert:
        cert_key = "supp_cert_deep_audit"
    elif has_basic_cert:
        cert_key = cert_type if cert_type else "supp_cert_onsite"
    else:
        cert_key = ""

    # ---- 按身份匹配模板（d1_score: 3=认证工厂 2=工厂直供 1=贸易商） ----
    if d1_score == 0 and d2_score == 0 and d3_score == 0:
        return "supplier_verdict_t0", {}

    if d1_score == 3:  # 认证工厂
        if is_old and has_deep_cert:
            return "supplier_verdict_t1", {"years": str(years), "cert_key": cert_key}
        if is_old and not has_deep_cert:
            return "supplier_verdict_t2", {"years": str(years)}
        return "supplier_verdict_t3", {
            "desc_key": desc_key, "years_n": str(years),
            "reason_keys": reason_keys if reason_keys else ["supp_fb_limited"]
        }

    if d1_score == 2:  # 工厂直供
        if is_old and has_any_cert:
            return "supplier_verdict_t4", {"years": str(years), "cert_key": cert_key}
        if is_old and not has_any_cert:
            return "supplier_verdict_t5", {"years": str(years)}
        return "supplier_verdict_t6", {"desc_key": desc_key, "years_n": str(years)}

    # d1_score == 1 or 0（贸易商 / 数据不足）
    if is_old and has_any_cert:
        return "supplier_verdict_t7", {"years": str(years), "cert_key": cert_key}
    return "supplier_verdict_t8", {
        "reason_keys": reason_keys if reason_keys else ["supp_fb_insufficient"]
    }


# ====================================================================
# 综合评判（产品 + 供应商 → 拿样建议）
# ====================================================================

def evaluate_summary(product_result: dict[str, Any], supplier_result: dict[str, Any]) -> dict[str, Any]:
    """综合产品 + 供应商评判 → 拿样建议。

    输入 evaluate_product() 和 evaluate_supplier() 的输出，
    输出综合结论（用于 inspect.html Card ① 底部）。
    """
    p_score: int = product_result.get("score", 0)
    s_score: int = supplier_result.get("score", 0)
    s_grade: str = supplier_result.get("grade", "")

    # 综合判定
    if p_score >= 12 and s_score >= 7:
        summary_key = "summary_go"
        summary_emoji = "🟢"
    elif p_score >= 8 and s_score >= 4:
        summary_key = "summary_ok"
        summary_emoji = "🟡"
    elif p_score >= 5:
        summary_key = "summary_check"
        summary_emoji = "🟡"
    else:
        summary_key = "summary_skip"
        summary_emoji = "🔴"

    # headline key（2 种）
    if summary_key in ("summary_go", "summary_ok"):
        headline_key = "summary_headline_go"
    else:
        headline_key = "summary_headline_caution"

    # reason key（4 种，对应 4 档）
    suffix: str = summary_key.split("_")[1]  # "go" / "ok" / "check" / "skip"
    reason_key: str = f"summary_reason_{suffix}"

    return {
        "verdict": _verdict(summary_key),
        "headline": _verdict(headline_key, emoji=summary_emoji),
        "reason": _verdict(reason_key),
        "product_score": f"{p_score}/15",
        "supplier_score": f"{s_score}/9",
    }


# ====================================================================
# 辅助
# ====================================================================

def _score_grade(score: int, max_score: int) -> str:
    """分数 → 前端 CSS class 名（go / ok / bad / none）。"""
    ratio: float = score / max_score if max_score > 0 else 0
    if ratio >= 0.75:
        return "go"
    elif ratio >= 0.5:
        return "ok"
    elif ratio > 0:
        return "bad"
    return "none"
