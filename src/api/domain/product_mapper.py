"""1688 商品数据映射 — Apify 原始 JSON → 标准化数据。

纯函数，零外部 API/DB 依赖。仅依赖 config.CNY_USD_RATE（汇率常量）。
覆盖风险清单：
  #8  字段级容错 — 所有字段取值前检查存在性，缺字段不崩溃
"""

from typing import Any, cast

from config import Config


# ====================================================================
# 公开入口
# ====================================================================

def map_raw(raw: dict[str, Any], original_url: str, offer_id: str) -> dict[str, Any]:
    """Apify 原始 JSON → 标准化数据（字段级容错，风险 #8）。

    所有字段取值前检查存在性，缺字段不崩溃。
    """
    price_data: dict[str, Any] = cast(dict[str, Any], raw.get("price")) or {}
    supplier: dict[str, Any] = cast(dict[str, Any], raw.get("supplier")) or {}
    flags: dict[str, Any] = cast(dict[str, Any], supplier.get("flags")) or {}
    stats: dict[str, Any] = cast(dict[str, Any], supplier.get("stats")) or {}
    shipping: dict[str, Any] = cast(dict[str, Any], raw.get("shipping")) or {}

    price_low_cny: Any = cast(float, price_data.get("min")) or 0
    price_high_cny: Any = cast(float, price_data.get("max")) or price_low_cny
    location: str = cast(str, shipping.get("location")) or ""

    # SKU 变体（Apify 键名: skuImages，字段: name/imgUrl）
    _raw_skus: Any = raw.get("skuImages") or raw.get("skuList") or raw.get("skus")
    sku_list: list[dict[str, Any]] = _raw_skus if isinstance(_raw_skus, list) else []  # type: ignore[reportUnnecessaryIsInstance]

    # 阶梯价格
    price_tiers = _extract_price_tiers(raw)

    # 数据完整度信号（三层金字塔：认证 + 年限）
    _tier, _tier_reason = _data_tier(flags, supplier.get("tpYear"))

    return {
        # 产品信息
        "title": raw.get("title", ""),
        "image": (raw.get("images") or [""])[0] if raw.get("images") else "",
        "images": (raw.get("images") or [])[:5],
        "priceLow": round(_safe_float(price_low_cny) / Config.CNY_USD_RATE, 2) if price_low_cny else None,
        "priceHigh": round(_safe_float(price_high_cny) / Config.CNY_USD_RATE, 2) if price_high_cny else None,
        "priceCNY": {"low": _safe_float(price_low_cny), "high": _safe_float(price_high_cny)},
        "moq": raw.get("minOrderQuantity"),
        "itemUrl": original_url or raw.get("detailUrl", ""),
        "specs": _filter_specs(raw.get("specs", []) or []),
        "unit": raw.get("unit", ""),
        "offerId": offer_id,

        # 产品指标
        "return7day": "OK" if _has_tag(raw.get("serviceLabels", []) or [], "7天")
                            or _has_tag(raw.get("serviceLabels", []) or [], "退货") else "NO",
        "sold": raw.get("saledCount"),
        "wantBuyCount": raw.get("wantBuyCount", 0),

        # 产品标签（Badge 行）
        "badgeLabels": _build_badge_labels(
            raw.get("productFlags", {}) or {},
            raw.get("serviceLabels", []) or [],
        ),

        # 工厂信息
        "supplierName": supplier.get("companyName", ""),
        "shop_rate": _parse_pct(
            stats.get("positiveReviewRate")
            or _raw_card_value(stats, "goodRate")
            or supplier.get("positiveReviewRate")
        ),
        "shop_years": supplier.get("tpYear"),
        "repurchase": _parse_pct(
            stats.get("repeatRate")
            or _raw_card_value(stats, "byrRepeatRate")
            or _factory_tag_value(supplier, "回头率")
            or supplier.get("repeatRate")
        ),
        "shippingLocation": location,
        "industryCluster": _industry_cluster(location),
        "deliveryDays": shipping.get("deliveryDays"),
        "freeSample": _has_tag(raw.get("serviceLabels", []) or [], "免费拿样"),

        # 工厂身份 + 认证 + 排名
        "sellerType": supplier.get("sellerType", ""),
        "sellerTypeLabel": _SELLER_TYPE_MAP.get(supplier.get("sellerType", ""), ""),
        "factoryFlags": _build_factory_flags(flags),
        "certType": _safe_cert_type(supplier.get("certification")),
        "certReportUrl": _safe_cert_url(supplier.get("certification")),
        "shopUrl": supplier.get("shopUrl", ""),
        "rankText": (cast(dict[str, Any], supplier.get("rank")) or {}).get("text", ""),  # type: ignore[reportUnknownMemberType]
        "sellerTierLabel": _trust_bar_label(flags),

        # 数据完整度信号（三层金字塔）
        "dataTier": _tier,
        "dataTierReason": _tier_reason,

        # 回头客 / 跨境买家
        "repeatBuyers": stats.get("repeatBuyers") or _raw_card_value(stats, "byrRepeatCustomer") or "",
        "crossBorderBuyers": stats.get("crossBorderBuyers") or _raw_card_value(stats, "kjByrNum90D") or "",

        # SKU + 阶梯价（供前端渲染）
        "skus": sku_list[:6] if sku_list else [],
        "price_tiers": price_tiers,
    }


# ====================================================================
# 工具函数（供 analyze_svc 使用）
# ====================================================================

# ====================================================================
# 标签映射常量
# ====================================================================

_SELLER_TYPE_MAP: dict[str, str] = {
    "yuantou_flagship": "源头旗舰",
    "shili_factory": "实力工厂",
    "super_factory": "超级工厂",
    "tp_factory": "通品工厂",
    "normal": "普通商家",
}

_FACTORY_FLAG_MAP: dict[str, str] = {
    "isFactory": "生产厂家",
    "isTpFactory": "通品工厂",
    "isShiliFactory": "实力工厂",
    "isSuperFactory": "超级工厂",
    "isYuantouFlagship": "源头旗舰",
    "isEaseBuyDealer": "工厂直供",
}

_BADGE_FLAG_MAP: dict[str, tuple[str, str]] = {
    # key → (label, css_class)
    "isFreeSample": ("免费拿样", "green"),
    "isBuyerProtection": ("买家保障", "gold"),
    "isCrossBorder": ("跨境专供", "blue"),
    "isWholesale": ("批发价", "green"),
    "isSupportMix": ("支持混批", "green"),
}

_SERVICE_BADGE_MAP: dict[str, str] = {
    "7天": "7天无理由退货",
    "退货": "7天无理由退货",
    "免费拿样": "免费拿样",
    "包邮": "包邮",
}


# ====================================================================
# 映射辅助函数
# ====================================================================

def _build_badge_labels(product_flags: dict[str, Any], service_labels: list[str]) -> list[dict[str, str]]:
    """从 productFlags + serviceLabels 构建 Badge 标签数组。"""
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for key, (label, cls) in _BADGE_FLAG_MAP.items():
        if product_flags.get(key) and label not in seen:
            result.append({"label": label, "class": cls})
            seen.add(label)
    for tag in service_labels:
        label = _SERVICE_BADGE_MAP.get(tag, tag)
        if label not in seen:
            result.append({"label": label, "class": "green"})
            seen.add(label)
    return result


def _trust_bar_label(flags: dict[str, Any]) -> str:
    """trust-bar 简化标签：isFactory=True→源头工厂, False→贸易商。

    详细等级（旗舰/超级/实力/普通）在工厂 Tab 展示。
    """
    return "源头工厂" if flags.get('isFactory') else "贸易商"


def _data_tier(flags: dict[str, Any], shop_years: Any) -> tuple[str, str]:
    """数据完整度信号：三层金字塔（认证 + 年限）。

    Returns:
        (tier, reason) — tier: "sufficient" | "partial" | "limited"
    """
    # 高级认证：平台花钱验证过的（超级工厂/实力工厂/源头旗舰等），不含自声称 isFactory
    has_advanced_cert: bool = bool(
        flags.get('isYuantouFlagship') or flags.get('isSuperFactory')
        or flags.get('isShiliFactory') or flags.get('isHyper')
        or flags.get('isChtMember')
    )
    is_factory: bool = bool(flags.get('isFactory'))
    years: float = 0
    if shop_years is not None:
        try:
            years = float(shop_years)
        except (ValueError, TypeError):
            years = 0

    if has_advanced_cert and years >= 2:
        return 'sufficient', '平台验厂认证 + 经营 2 年以上 · 拿样风险低'
    elif has_advanced_cert:
        return 'partial', '有平台验厂认证，经营不足 2 年 · 建议验货'
    elif is_factory and years >= 1:
        return 'partial', '生产厂家，经营 1 年以上 · 建议拿样验证'
    elif years >= 1:
        return 'partial', '无工厂认证，经营 1 年以上 · 建议拿样验证'
    else:
        return 'limited', '无官方认证，经营不足 1 年 · 建议人工核实'


def _build_factory_flags(flags: dict[str, Any]) -> str:
    """从 supplier.flags 提取工厂实力描述文字。

    isFactory=False 时不输出工厂标签。
    """
    if not flags.get('isFactory'):
        return "非生产厂家"

    parts: list[str] = []
    for key, label in _FACTORY_FLAG_MAP.items():
        if flags.get(key):
            parts.append(label)
    return " · ".join(parts) if parts else ""


def _safe_cert_type(cert: Any) -> str:
    if isinstance(cert, dict):  # type: ignore[reportUnnecessaryIsInstance]
        _c: dict[str, Any] = cast(dict[str, Any], cert)
        return str(_c.get("type", ""))
    return ""


def _safe_cert_url(cert: Any) -> str:
    if isinstance(cert, dict):  # type: ignore[reportUnnecessaryIsInstance]
        _c: dict[str, Any] = cast(dict[str, Any], cert)
        return str(_c.get("reportUrl", ""))
    return ""


def _extract_price_tiers(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """提取阶梯价格。Apify 返回格式：[{quantityMin, quantityMax, price}, ...]"""
    _raw_tiers: Any = raw.get("quantityPrices") or raw.get("priceRanges") or raw.get("priceRange")
    tiers: list[dict[str, Any]] = _raw_tiers if isinstance(_raw_tiers, list) else []  # type: ignore[reportUnnecessaryIsInstance]
    result: list[dict[str, Any]] = []
    for t in tiers:
        result.append({
            "qty_min": t.get("quantityMin") or t.get("begin") or t.get("qty_min"),
            "qty_max": t.get("quantityMax") or t.get("end") or t.get("qty_max"),
            "unit_price": t.get("price") or t.get("unit_price"),
        })
    return result


def _filter_specs(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """过滤关键规格（风险 #8：字段级容错）。"""
    KEYS = {"材质", "品牌", "颜色", "规格", "尺寸", "风格", "货号", "重量", "包装", "工艺", "类别", "骨架"}
    result: list[dict[str, str]] = []
    for s in specs:
        name = str(s.get("name", "")).strip()
        value = str(s.get("value", "")).strip()
        if name in KEYS and value and value != "咨询客服" and len(value) < 30:
            result.append({"name": name, "value": value})
    result.sort(key=lambda x: 0 if x["name"] in ("材质", "工艺", "类别") else 1)
    return result[:8]


def _has_tag(tags: list[str], keyword: str) -> bool:
    return any(keyword in str(t) for t in tags)


def _safe_float(val: Any) -> float:
    """安全转 float。非法值返回 0，不抛异常（Apify 字段格式不稳定）。"""
    if val is None:
        return 0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0


def _parse_pct(val: Any) -> float | None:
    """解析百分比字段。支持 '95.3%' / 0.953 / 95.3 多种格式。"""
    if val is None:
        return None
    if isinstance(val, str):
        val = val.replace("%", "").strip()
    try:
        v = float(val)
        return round(v * 100 if v < 1 else v, 1)
    except (ValueError, TypeError):
        return None


def _raw_card_value(stats: dict[str, Any], code: str) -> Any:
    """从 stats.rawCardDetail 数组中按 code 取值。"""
    for item in (stats.get('rawCardDetail') or []):  # type: ignore[reportUnknownMemberType]
        if isinstance(item, dict):  # type: ignore[reportUnnecessaryIsInstance]
            item_dict: dict[str, Any] = cast(dict[str, Any], item)
            if item_dict.get('code') == code:
                return item_dict.get('value')
    return None


def _factory_tag_value(supplier: dict[str, Any], keyword: str) -> Any:
    """从 supplier.factoryTags 数组中按 text 关键词模糊匹配取值。"""
    for item in (supplier.get('factoryTags') or []):  # type: ignore[reportUnknownMemberType]
        if isinstance(item, dict):  # type: ignore[reportUnnecessaryIsInstance]
            item_dict: dict[str, Any] = cast(dict[str, Any], item)
            if keyword in str(item_dict.get('text', '')):
                return item_dict.get('value')
    return None


def _industry_cluster(location: str) -> str:
    if not location:
        return ""
    MAP = {
        "义乌": "中国小商品集散中心", "广州": "服装/箱包/皮具产业带",
        "深圳": "3C 电子/跨境电商货源地", "晋江": "运动鞋服产业带",
        "南通": "家纺产业带", "泉州": "鞋服箱包产业带",
        "东莞": "电子/玩具/模具产业带", "佛山": "家具/陶瓷产业带",
        "杭州": "女装/电商供应链中心", "温州": "鞋革/五金/眼镜产业带",
        "宁波": "小家电/文具产业带", "绍兴": "纺织面料产业带",
        "澄海": "玩具产业带", "永康": "五金/杯壶产业带",
        "诸暨": "袜子/珍珠产业带", "潮州": "陶瓷/卫浴产业带",
    }
    for key, desc in MAP.items():
        if key in location:
            return desc
    return ""
