"""1688 商品 display JSON 构建器 — 3 路处理。

Path 1 (英文直接): 数字/公式字段，不调 AI — 10 字段
Path 2 (字典查表): sellerLabel + badge.mixed 用 4 语言字典 — 2 字段
Path 3 (中文原文): 复杂文本，后续由 ai_verdict_svc.build_with_ai 调 Qwen 翻译 — 18 字段（16 标量 + 2 数组）

纯函数，零外部依赖。每个 builder 独立 try/except，单个崩溃不阻塞整体。
"""

import json
import re
from pathlib import Path
from typing import Any, cast

from domain.evaluate import evaluate_product, evaluate_supplier, evaluate_summary
from utils.i18n_core import LANGS, cjk_in
from utils.logger import get_logger

logger = get_logger(__name__)

# 残留汉字清理（AI 未完全转写字段的安全网）
_CJK_RE = re.compile(r"[一-鿿]")

# ---- 加载配置 JSON ----
_HERE = Path(__file__).parent
with open(_HERE.parent / "data" / "glossary.json", "r", encoding="utf-8") as _f:
    GL = json.load(_f)
# 旧中文键 → ASCII 键过渡表（glossary.json _aliases，键全 ASCII 化后本表随旧引用清理而删）
_ALIAS: dict[str, str] = cast(dict[str, str], GL.get("_aliases", {}))


def _glossary(key: str, lang: str, default: str = "") -> str:
    """glossary.json 查表（结构：{key: {en, vi, th, zh}}）。"""
    key = _ALIAS.get(key, key)
    entry: Any = GL.get(key, {})
    if not isinstance(entry, dict):
        return default or key
    if not entry:  # key 不在 glossary 中 → 返回 default，绝不泄漏 raw key
        return default
    d: dict[str, str] = cast(dict[str, str], entry)
    # lang → en → zh 降级链；跳过 "TODO" 占位符
    text: str = d.get(lang, "")
    if (not text or text == "TODO") and lang != "en":
        text = d.get("en", "")
    if not text or text == "TODO":
        text = d.get("zh", "")
    if not text or text == "TODO":
        text = default
    return text

# ====================================================================
# Path 1: 星级符号（Unicode，不需要翻译）
# ====================================================================

_STAR_SYMBOLS: dict[str, str] = {
    "sufficient": "★★★",
    "partial": "★★☆",
    "limited": "★☆☆",
}

# display 顶层 key 全集（新增 key 必须同步更新此集合 + 测试 expected_keys）
_EXPECTED_KEYS: set[str] = {
    "title", "titleOrig", "images", "videoUrl", "itemUrl", "offerId",
    "price", "trustBar", "badges", "specs", "sales",
    "skus", "priceTiers", "factory",
    "productEval", "supplierEval", "summaryLine",
}


def _cjk_machine_gate(d: dict[str, Any], lang: str) -> None:
    """非 zh 出口闸：工厂透传中文字段（认证/徽章/发货地）翻译或置空，specs 中文不渲染。

    zh 路径原样返回。AI 覆盖的内容字段（title/判词等）不在此闸内（各自走翻译/校验）。
    """
    if lang == "zh":
        return
    f = d.get("factory")
    if isinstance(f, dict):
        f = cast(dict[str, Any], f)
        for field in ("certType", "factoryFlags", "shippingLocation"):
            v = f.get(field)
            if not isinstance(v, str) or not cjk_in(v):
                continue
            cand = _glossary(v, lang, "") if field == "certType" else ""
            if field == "certType" and (not cand or cjk_in(cand)):
                _tail = v.rsplit("·", 1)[-1] if "·" in v else ""
                cand = _tail.upper() if _tail and _tail.isascii() else ""
            f[field] = cand
        # 名称类字段：AI 未完全转写（如 "Yiwu Rongcheng工艺品 Company"）→ 去残留汉字，保拉丁段
        v = f.get("supplierName")
        if isinstance(v, str) and cjk_in(v):
            f["supplierName"] = _CJK_RE.sub("", v).strip()
    se = d.get("supplierEval")
    if isinstance(se, dict):
        se = cast(dict[str, Any], se)
        for field in ("companyName", "shippingLocation"):
            v = se.get(field)
            if isinstance(v, str) and cjk_in(v):
                se[field] = _CJK_RE.sub("", v).strip() if field == "companyName" else ""
    specs = d.get("specs")
    if isinstance(specs, list):
        d["specs"] = [
            s for s in cast(list[dict[str, Any]], specs)
            if not (cjk_in(s.get("name", "")) or cjk_in(s.get("value", "")))
        ]


def build_display(mapped: dict[str, Any], lang: str = "en", money: dict[str, Any] | None = None) -> dict[str, Any]:
    """从 mapped 构建 display JSON。

    Args:
        mapped: product_mapper.map_raw() 输出
        lang: 目标语言代码（en/vi/th/zh），用于 Path 2 字典查表
        money: 目标货币配置（per_cny 换算系数），None 保持人民币（zh）

    Returns:
        display JSON。Path 1 英文，Path 2 字典值，Path 3 中文（待翻译）。
        构建失败返回最小可用结构（不抛异常）。
    """
    # 兜底 lang（不支持的语言默认英文）
    safe_lang: str = lang if lang in LANGS else "en"

    # 验货报告评判（domain 内部组合：evaluator → display）
    product_raw: dict[str, Any] = evaluate_product(mapped)
    supplier_raw: dict[str, Any] = evaluate_supplier(mapped)

    try:
        d: dict[str, Any] = {
            # ---- 基础信息 ----
            "title": _s(mapped.get("title")),
            "titleOrig": _s(mapped.get("title")),
            "images": mapped.get("images") or [],
            "videoUrl": _s(mapped.get("videoUrl")),
            "itemUrl": _s(mapped.get("itemUrl")),
            "offerId": _s(mapped.get("offerId")),

            # ---- 价格（数字，Path 1） ----
            "price": _build_price(mapped, safe_lang, money),

            # ---- 信任条（Path 1 + Path 2） ----
            "trustBar": _build_trust_bar(mapped, safe_lang),

            # ---- Badge 行（Path 1 + Path 2） ----
            "badges": _build_badges(mapped, safe_lang),

            # ---- 规格（Path 3：中文原文） ----
            "specs": _build_specs(mapped),

            # ---- 销售数据（Path 3 解释文案） ----
            "sales": _build_sales(mapped, safe_lang),

            # ---- SKU（原样透传） ----
            "skus": mapped.get("skus") or [],

            # ---- 阶梯价格（纯数字，Path 1） ----
            "priceTiers": _build_price_tiers(mapped, money),

            # ---- 工厂信息（Path 2 + Path 3） ----
            "factory": _build_factory(mapped, safe_lang),

            # ---- 验货报告评判（evaluator → 前端 display） ----
            "productEval": _build_product_eval(product_raw, mapped, safe_lang),
            "supplierEval": _build_supplier_eval(supplier_raw, mapped, safe_lang),
            "summaryLine": _build_summary_line(product_raw, supplier_raw, safe_lang),
        }

        # ---- 缺 key 告警 ----
        missing = _EXPECTED_KEYS - set(d)
        if missing:
            logger.warning(f"build_display missing keys: {missing}")

        # ---- 非 zh 机器字段 CJK 门禁（中文透传不得发给前端） ----
        _cjk_machine_gate(d, safe_lang)

        return d
    except Exception:
        # 整体构建失败 → 最小可用结构
        return {
            "title": _s(mapped.get("title", "")),
            "titleOrig": _s(mapped.get("title", "")),
            "price": _build_price(mapped, safe_lang, money),
            "trustBar": {},
            "badges": [],
            "specs": [],
            "sales": {},
            "skus": [],
            "priceTiers": [],
            "factory": {},
            "productEval": {},
            "supplierEval": {},
            "summaryLine": {},
        }


# ====================================================================
# 各模块 builder（独立 try/except，单体崩溃不影响其他）
# ====================================================================


def _build_price(mapped: dict[str, Any], lang: str, money: dict[str, Any] | None = None) -> dict[str, Any]:
    cny: Any = mapped.get("priceCNY") or {}
    cny_d = cast(dict[str, Any], cny) if isinstance(cny, dict) else {}
    raw_unit: str = _s(mapped.get("unit"))
    per_cny: float = float(money["per_cny"]) if money else 1.0  # 汇率 svc 层注入，None 保持人民币
    low_cny: float = float(cny_d.get("low", 0) or 0)
    high_cny: float = float(cny_d.get("high", 0) or 0)
    price: dict[str, Any] = {
        "low": round(low_cny * per_cny, 6),
        "high": round(high_cny * per_cny, 6),
        "moq": mapped.get("moq"),
        "unit": _glossary(f"unit_{raw_unit}", lang, raw_unit),  # type: ignore[reportUnknownMemberType]
    }
    # 拿样美元价（前端定金用）：money 注入 usd_per_cny 才输出，None（纯模板调用）不输出
    usd_factor = float(money["usd_per_cny"]) if money and money.get("usd_per_cny") else None
    if usd_factor:
        price["usd"] = {"low": round(low_cny * usd_factor, 6), "high": round(high_cny * usd_factor, 6)}
    return price


def _build_price_tiers(mapped: dict[str, Any], money: dict[str, Any] | None) -> list[dict[str, Any]]:
    """阶梯价：money 注入时把 unit_price 换成目标货币，None 保持人民币。"""
    tiers: list[dict[str, Any]] = mapped.get("price_tiers") or []
    if not money or not tiers:
        return tiers
    per_cny: float = float(money["per_cny"])
    out: list[dict[str, Any]] = []
    for t in tiers:
        up = t.get("unit_price")
        if isinstance(up, (int, float)):
            out.append({**t, "unit_price": round(float(up) * per_cny, 6)})
        else:
            out.append(t)
    return out


def _build_trust_bar(mapped: dict[str, Any], lang: str) -> dict[str, Any]:
    """信任条：Path 1 英文数词 + Path 2 sellerLabel。"""
    try:
        raw_label: str = _s(mapped.get("sellerTierLabel"))
        label: str = _glossary(raw_label, lang, raw_label)

        sold_n: str = _fmt_num(mapped.get("sold")) if mapped.get("sold") else ""
        sold_str: str = _glossary("trust_sold_fmt", lang).replace("{n}", sold_n) if sold_n else ""

        years: Any = mapped.get("shop_years")
        years_str: str = _glossary("trust_years_fmt", lang).replace("{n}", str(years)) if years else ""

        tier: str = _s(mapped.get("dataTier"))
        stars: str = _STAR_SYMBOLS.get(tier, "")
        tier_label: str = _glossary(f"star_{tier}_label", lang, "") if tier else ""

        return {
            "label": label,
            "sold": sold_str,
            "years": years_str,
            "stars": stars,
            "tier": tier_label,
            "tierReason": _glossary(_s(mapped.get("dataTierReason")), lang),
        }
    except Exception:
        return {}


def _build_badges(mapped: dict[str, Any], lang: str) -> list[dict[str, str]]:
    """Badge 行：Path 1 英文 + Path 2 混批字典。"""
    badges: list[dict[str, str]] = []
    try:
        # 7 天退货
        if mapped.get("return7day") == "OK":
            t_7d: str = _glossary("svc_7day_return", lang, "7-Day Returns")
            badges.append({
                "text": t_7d,
                "html": f'<span class="badge-sm green">{t_7d}</span>',
            })

        # (v2 已移除「回头率」徽章：复购率是店铺级数据，产品顶部 badge 属数据归属错误，
        #  复购/好评已在供应商验证卡 supp_dim_d4/d5 展示，此处不冒充产品卖点)

        # 混批（Path 2：字典查表，glossary.json）
        badge_labels: list[dict[str, Any]] = mapped.get("badgeLabels") or []
        has_mixed: bool = any(
            b.get("label") == "支持混批"
            for b in badge_labels
        )
        if has_mixed:
            mixed_text: str = _glossary("svc_mixed_batch", lang, "Mixed Batch OK")
            badges.append({
                "text": mixed_text,
                "html": f'<span class="badge-sm green">{mixed_text}</span>',
            })
    except Exception:
        pass
    return badges


def _build_specs(mapped: dict[str, Any]) -> list[dict[str, str]]:
    """规格参数：Path 3 中文原文（name + value 都可能含中文）。"""
    specs: Any = mapped.get("specs") or []
    if not isinstance(specs, list):
        return []
    result: list[dict[str, str]] = []
    for s in cast(list[Any], specs):
        if isinstance(s, dict):
            sd = cast(dict[str, Any], s)
            result.append({
                "name": _s(sd.get("name")),
                "value": _s(sd.get("value")),
            })
    return result


def _build_sales(mapped: dict[str, Any], lang: str) -> dict[str, str]:
    """销售数据：数字格式 + 解释文案（glossary 查表）。"""
    sold: Any = mapped.get("sold")
    sold_n: str = _fmt_num(sold) if sold else ""
    sold_str: str = _glossary("sales_sold_fmt", lang).replace("{n}", sold_n) if sold_n else ""

    # 解释文案
    explain: str = ""
    try:
        sold_num: float = float(sold) if sold else 0
    except (ValueError, TypeError):
        sold_num = 0
    if sold_num >= 1000:
        explain = _glossary("explain_sales_high", lang)

    return {"sold": sold_str, "explain": explain}


def _build_factory(mapped: dict[str, Any], lang: str) -> dict[str, Any]:
    """工厂信息：Path 2 sellerLabel + Path 3 中文文案。"""
    try:
        raw_label: str = _s(mapped.get("sellerTierLabel"))
        seller_label: str = _glossary(raw_label, lang, raw_label)

        factory_flags: str = _s(mapped.get("factoryFlags"))
        cert_type: str = _s(mapped.get("certType"))
        rank_text: str = _s(mapped.get("rankText"))

        # ---- 解释文案（全部从 glossary 取，4 语言预翻译） ----

        # 商家身份解释
        seller_explain: str = ""
        if raw_label == "源头工厂":
            seller_explain = _glossary("explain_seller_factory", lang)
        elif raw_label == "贸易商":
            seller_explain = _glossary("explain_seller_trader", lang)

        # 工厂实力解释
        flags_explain: str = ""
        is_trader: bool = "非生产厂家" in factory_flags
        if is_trader:
            flags_explain = _glossary("explain_flags_trader", lang)
        elif "超级工厂" in factory_flags:
            flags_explain = _glossary("explain_flags_super", lang)
        elif "源头旗舰" in factory_flags:
            flags_explain = _glossary("explain_flags_flagship", lang)
        elif "实力工厂" in factory_flags:
            flags_explain = _glossary("explain_flags_shili", lang)
        elif factory_flags and factory_flags != "非生产厂家":
            flags_explain = _glossary("explain_flags_self_claimed", lang)

        # 认证解释
        cert_explain: str = ""
        if cert_type:
            cert_explain = _glossary("explain_cert_has", lang)
        else:
            cert_explain = _glossary("explain_cert_none", lang)

        # 排名解释
        rank_explain: str = ""
        if not rank_text:
            rank_explain = _glossary("explain_rank_none", lang)

        # 产业带解释：mapper 输出 glossary KEY → 查表得描述 → 填入解释模板
        industry_key: str = _s(mapped.get("industryCluster"))
        location: str = _s(mapped.get("shippingLocation"))
        industry_desc: str = _glossary(industry_key, lang) if industry_key else ""
        industry_explain: str = ""
        if industry_key:
            industry_explain = _glossary("explain_industry_fmt", lang).format(industry=industry_desc)

        # emoji 前缀从 glossary 取（各语言相同但统一管理）
        factory_emoji: str = _glossary("emoji_factory", lang, "🏭 ")
        rank_emoji: str = _glossary("emoji_rank", lang, "🏆 ")

        return {
            "sellerLabel": f"{factory_emoji}{seller_label}" if seller_label else "",
            "sellerExplain": seller_explain,
            "companyNameExplain": _glossary("explain_company_name", lang),
            "certType": cert_type,
            "certExplain": cert_explain,
            "certReportUrl": _s(mapped.get("certReportUrl")),
            "shopUrl": _s(mapped.get("shopUrl")),
            "factoryFlags": factory_flags,
            "flagsExplain": flags_explain,
            "rankText": f"{rank_emoji}{rank_text}" if rank_text else "",
            "rankExplain": rank_explain,
            "supplierName": _s(mapped.get("supplierName")),
            "shippingLocation": location,
            "industryCluster": industry_explain,
            "industryExplain": _glossary("explain_industry_cluster", lang),
        }
    except Exception:
        return {}


# ====================================================================
# 验货报告 builder（新产品 + 供应商 evaluator → inspect.html）
# ====================================================================


def _build_product_eval(product_raw: dict[str, Any], mapped: dict[str, Any], lang: str) -> dict[str, Any]:
    """产品验证卡片：evaluate_product() 输出 → 前端 display JSON。

    翻译维度 name/label/data/ref + summary + stockLevel，全部走 glossary。
    """
    try:
        dims_out: list[dict[str, Any]] = []
        for dim in cast(list[dict[str, Any]], product_raw.get("dimensions") or []):
            if not isinstance(dim, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
                continue
            d_out: dict[str, Any] = {
                "key": dim.get("key", ""),
                "score": dim.get("score", 0),
                "icon": dim.get("icon", ""),
            }

            # name
            name_key: str = str(dim.get("name_key", ""))
            d_out["name"] = _glossary(name_key, lang) if name_key else ""

            # label（空则前端降级到 icon+name）
            label_key: str = str(dim.get("label_key", ""))
            d_out["label"] = _glossary(label_key, lang) if label_key else ""

            # data：优先 static key（D5），其次 format string（D1-D4）
            data_key: str = str(dim.get("data_key", ""))
            if data_key:
                d_out["data"] = _glossary(data_key, lang)
            else:
                data_fmt: str = str(dim.get("data_fmt", ""))
                if data_fmt and dim.get("data_params"):
                    # D3：{price}/{moq}/{unit} 多参数
                    params: dict[str, Any] = dict(dim["data_params"])
                    if "unit" in params:
                        unit_cn: str = str(params["unit"])
                        params["unit"] = _glossary(f"unit_{unit_cn}", lang, unit_cn)
                    if "price" in params and isinstance(params["price"], (int, float)):
                        params["price"] = f"{params['price']:.2f}"
                    d_out["data"] = _glossary(data_fmt, lang).format(**params)
                elif data_fmt and dim.get("data_num") is not None:
                    # D1/D2/D4：{n} 格式
                    d_out["data"] = _glossary(data_fmt, lang).format(
                        n=_fmt_dim_num(dim["data_num"], lang)
                    )
                else:
                    d_out["data"] = ""
            # 无数据 → 标记 na，前端灰色弱化
            if not d_out.get("data"):
                d_out["data"] = _glossary("no_data", lang, "")
                d_out["na"] = True

            # ref
            ref_fmt: str = str(dim.get("ref_fmt", ""))
            if ref_fmt and dim.get("ref_num") is not None:
                d_out["ref"] = _glossary(ref_fmt, lang).format(
                    n=_fmt_dim_num(dim["ref_num"], lang)
                )
            else:
                d_out["ref"] = ""

            dims_out.append(d_out)

        # 库存档位（商业判断，glossary 翻译）
        stock_level: dict[str, str] | None = None
        stock_raw: Any = mapped.get("stock")
        if stock_raw is not None:
            try:
                stock_num: int = int(float(stock_raw))
                if stock_num > 100:
                    stock_level = {"level": "ok", "text": _glossary("stock_level_ok", lang)}
                elif stock_num > 0:
                    stock_level = {"level": "low", "text": _glossary("stock_level_low", lang)}
                else:
                    stock_level = {"level": "unknown", "text": _glossary("stock_level_unknown", lang)}
            except (ValueError, TypeError):
                pass

        result: dict[str, Any] = {
            "score": product_raw.get("score", 0),
            "max_score": product_raw.get("max_score", 3.0),  # v2 加权满分 3.0（evaluate 恒给，此为兜底）
            "grade": product_raw.get("grade", ""),
            "summary": _format_verdict(product_raw.get("summary"), lang),
            "verdict": _format_verdict(product_raw.get("verdict"), lang),
            "dimensions": dims_out,
        }
        if stock_level:
            result["stockLevel"] = stock_level
        return result
    except Exception:
        logger.exception("_build_product_eval failed")
        return {}


def _build_supplier_eval(supplier_raw: dict[str, Any], mapped: dict[str, Any], lang: str) -> dict[str, Any]:
    """供应商验证卡片：evaluate_supplier() 输出 + mapped 附加信息 → 前端 display JSON。

    翻译维度 name/label/data/ref + grade + summary，全部走 glossary。
    """
    try:
        # 产业带描述（复用 _build_factory 的 glossary 查表逻辑）
        industry_key: str = _s(mapped.get("industryCluster"))
        location: str = _s(mapped.get("shippingLocation"))
        industry_desc: str = _glossary(industry_key, lang) if industry_key else ""
        industry_explain: str = ""
        if industry_key:
            industry_explain = _glossary("explain_industry_fmt", lang).format(industry=industry_desc)

        # 翻译维度
        dims_out: list[dict[str, Any]] = []
        for dim in cast(list[dict[str, Any]], supplier_raw.get("dimensions") or []):
            if not isinstance(dim, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
                continue
            d_out: dict[str, Any] = {
                "key": dim.get("key", ""),
                "score": dim.get("score", 0),
                "icon": dim.get("icon", ""),
            }

            # name
            name_key: str = str(dim.get("name_key", ""))
            d_out["name"] = _glossary(name_key, lang) if name_key else ""

            # label（空则前端降级到 icon+name）
            label_key: str = str(dim.get("label_key", ""))
            d_out["label"] = _glossary(label_key, lang) if label_key else ""

            # data：优先 static key，其次 format string，最后 data_text（ASCII 透传）
            data_key: str = str(dim.get("data_key", ""))
            if data_key:
                # 旧中文键 → ASCII（_aliases 过渡表）：display JSON data_key 恒 ASCII，前端逻辑按此判断
                data_key = _ALIAS.get(data_key, data_key)
                d_out["data"] = _glossary(data_key, lang)
                # 保留 data_key 供前端 JS 逻辑判断
                d_out["data_key"] = data_key
            else:
                data_fmt: str = str(dim.get("data_fmt", ""))
                if data_fmt and dim.get("data_num") is not None:
                    d_out["data"] = _glossary(data_fmt, lang).format(
                        n=_fmt_dim_num(dim["data_num"], lang)
                    )
                elif dim.get("data_text"):
                    # ASCII 认证类型（SGS/TUV）→ 原样透传
                    d_out["data"] = str(dim["data_text"])
                else:
                    d_out["data"] = ""

            # 无数据 → 标记 na，前端灰色弱化
            if not d_out.get("data"):
                d_out["data"] = _glossary("no_data", lang, "")
                d_out["na"] = True

            # ref：format string + num
            ref_fmt: str = str(dim.get("ref_fmt", ""))
            if ref_fmt and dim.get("ref_num") is not None:
                d_out["ref"] = _glossary(ref_fmt, lang).format(
                    n=_fmt_dim_num(dim["ref_num"], lang)
                )
            else:
                d_out["ref"] = ""

            dims_out.append(d_out)

        # ---- 帮助文本（条件产出，前端按 data_key 判断显隐） ----
        help_texts: dict[str, str] = {}
        for dim in dims_out:
            dk: str = str(dim.get("data_key", ""))
            if dk == "seller_strength_merchant":
                help_texts["verified"] = _glossary("supp_help_verified", lang)
            elif dk == "supp_dim_d2_data_no_cert":
                help_texts["noCert"] = _glossary("supp_help_no_cert", lang)
                help_texts["riskNoCert"] = _glossary("supp_risk_no_cert", lang)

        # 翻译 summary（_verdict 格式，identity_key 特殊处理）
        summary_raw: Any = supplier_raw.get("summary")
        summary_text: str = ""
        if summary_raw and isinstance(summary_raw, dict):
            s: dict[str, Any] = cast(dict[str, Any], summary_raw)
            sk: str = str(s.get("key", ""))
            sp: dict[str, Any] = s.get("params") or {}
            if "identity_key" in sp:
                sp["identity"] = _glossary(str(sp.pop("identity_key")), lang)
            template: str = _glossary(sk, lang)
            try:
                summary_text = template.format(**sp)
            except (KeyError, ValueError):
                summary_text = template

        return {
            "score": supplier_raw.get("score", 0),
            "max_score": supplier_raw.get("max_score", 3.0),  # v2 加权满分 3.0（evaluate 恒给，此为兜底）
            "grade": supplier_raw.get("grade", ""),           # CSS class: go/ok/bad/none
            "gradeText": _glossary(str(supplier_raw.get("grade_key", "")), lang),
            "summary": summary_text,
            "verdict": _format_verdict(supplier_raw.get("verdict"), lang),
            "dimensions": dims_out,
            "companyName": _s(mapped.get("supplierName")),
            "industryCluster": industry_explain,
            "shippingLocation": location,
            "helpTexts": help_texts,
        }
    except Exception:
        logger.exception("_build_supplier_eval failed")
        return {}


def _build_summary_line(product_raw: dict[str, Any], supplier_raw: dict[str, Any], lang: str) -> dict[str, Any]:
    """综合结论：产品 + 供应商 → 拿样建议（inspect.html Card ①）。"""
    try:
        summary: dict[str, Any] = evaluate_summary(product_raw, supplier_raw)
        # 提取 headline key 用于 short 字段（前端对比表用）
        headline_kv: dict[str, Any] = cast(dict[str, Any], summary.get("headline", {})) if isinstance(summary.get("headline"), dict) else {}
        headline_key: str = str(headline_kv.get("key", ""))
        return {
            "headline": _format_verdict(summary.get("headline"), lang),
            "reason": _format_verdict(summary.get("reason"), lang),
            "verdict": _format_verdict(summary.get("verdict"), lang),
            "short": _glossary(headline_key + "_short", lang),
            "product_score": summary.get("product_score", ""),
            "supplier_score": summary.get("supplier_score", ""),
            "grade": summary.get("grade", "none"),
        }
    except Exception:
        logger.exception("_build_summary_line failed")
        return {}


def _format_verdict(v: Any, lang: str) -> str:
    """从 {key, params} + glossary 拼出目标语言判词。

    兼容旧格式：如果 v 是 str（旧版中文判词），直接返回原文。
    """
    if not v:
        return ""
    if isinstance(v, str):
        return v  # 向后兼容旧格式
    if not isinstance(v, dict):
        return ""
    d: dict[str, Any] = cast(dict[str, Any], v)
    key: str = str(d.get("key", ""))
    if not key:
        return ""
    template: str = _glossary(key, lang)
    if not template:
        return ""
    params: dict[str, Any] = dict(d.get("params", {}))

    # 翻译 desc_key（供应商年限描述，可能含 {n} 占位符）
    if "desc_key" in params:
        desc_tpl: str = _glossary(str(params.pop("desc_key")), lang)
        years_n: str = str(params.pop("years_n", ""))
        if "{n}" in desc_tpl and years_n:
            params["desc"] = desc_tpl.format(n=years_n)
        else:
            params["desc"] = desc_tpl

    # 翻译 cert_key（供应商认证类型 key → 各语言文本）
    if "cert_key" in params:
        params["cert"] = _glossary(str(params.pop("cert_key")), lang)

    # 翻译 reason_keys（list of key → 各语言文本 → 拼接）
    if "reason_keys" in params:
        rks = params.pop("reason_keys")
        if isinstance(rks, list) and rks:
            sep: str = _glossary("supp_reason_sep", lang, "、")
            translated: list[str] = [_glossary(str(rk), lang, rk) for rk in cast(list[str], rks)]
            reason_str: str = sep.join(translated)
            params["reason"] = reason_str
            params["reasons"] = reason_str

    # 翻译参数中的中文单位（1688 原始中文 unit）
    if "unit" in params:
        unit_cn: str = str(params["unit"])
        unit_translated: str = _glossary(f"unit_{unit_cn}", lang)
        if unit_translated and unit_translated != unit_cn:
            params["unit"] = unit_translated

    # ---- 新判词系统参数 ----

    # good_part_keys: list of glossary key → resolve each → join（多证据合并一句，不额外占句数）
    sep_p: str = "、" if lang == "zh" else ", "
    if "good_part_keys" in params:
        gks: Any = params.pop("good_part_keys")
        if isinstance(gks, list) and gks:
            parts: list[str] = []
            for gk in cast(list[Any], gks):
                part_tpl: str = _glossary(str(gk), lang, str(gk))
                try:
                    parts.append(part_tpl.format(**params))
                except (KeyError, ValueError):
                    parts.append(part_tpl)
            params["good_parts"] = sep_p.join(parts) if parts else ""
        else:
            params["good_parts"] = ""

    # bad_part_keys: list of glossary key → resolve each → join（同上）
    if "bad_part_keys" in params:
        bks: Any = params.pop("bad_part_keys")
        if isinstance(bks, list) and bks:
            parts: list[str] = []
            for bk in cast(list[Any], bks):
                part_tpl: str = _glossary(str(bk), lang, str(bk))
                try:
                    parts.append(part_tpl.format(**params))
                except (KeyError, ValueError):
                    parts.append(part_tpl)
            params["bad_parts"] = sep_p.join(parts) if parts else ""
        else:
            params["bad_parts"] = ""

    # barrier_tip_key: glossary key → resolve → format with nested params (price, moq)
    if "barrier_tip_key" in params:
        tip_key: str = str(params.pop("barrier_tip_key"))
        tip_tpl: str = _glossary(tip_key, lang, tip_key)
        try:
            params["barrier_tip"] = tip_tpl.format(**params)
        except (KeyError, ValueError):
            params["barrier_tip"] = tip_tpl

    # action_key: glossary key → resolve
    if "action_key" in params:
        action_key: str = str(params.pop("action_key"))
        params["action"] = _glossary(action_key, lang, action_key)

    # risk_note_key: glossary key → resolve → {risk_note}（无风险时为空字符串）
    risk_note = ""
    if "risk_note_key" in params:
        rn_key: str = str(params.pop("risk_note_key"))
        risk_note = _glossary(rn_key, lang, rn_key)
    params["risk_note"] = risk_note

    try:
        rendered = template.format(**params)
    except (KeyError, ValueError):
        # 可选参数缺失：裁掉含未填占位的括号段（如"（{prod_num}）"），其余保留
        dropped = re.sub(r"[（(][^（）()]*\{[^}]*\}[^（）()]*[)）]", "", template)
        dropped = re.sub(r"\{[^}]*\}", "", dropped)
        logger.warning(f"_format_verdict format failed (optional parts dropped): key={key}")
        return dropped
    # 清理空括号：缺参参数填空串后留下的"（）"及尾随空格
    rendered = re.sub(r"\s*[（(]\s*[)）]\s*", "", rendered)
    return rendered.rstrip()


# ====================================================================
# 工具函数
# ====================================================================


def _s(val: Any) -> str:
    """安全转字符串，None/非字符串 → ''。"""
    if val is None:
        return ""
    return str(val)


def _fmt_dim_num(n: Any, lang: str = "") -> str:
    """维度数字格式化：8900 → '8,900'（ru: '8 900'），67.5 → '67,5'（ru）。千分位 + 保留小数。"""
    if n is None:
        return "0"
    try:
        v: float = float(n)
        if v == int(v):
            return f"{int(v):,}".replace(",", " " if lang == "ru" else ",")
        s: str = f"{v:,.1f}"
        s = s.rstrip("0").rstrip(".") if "." in s else s
        if lang == "ru":
            return s.replace(",", " ").replace(".", ",")
        return s
    except (ValueError, TypeError):
        return str(n)


def _fmt_num(n: Any) -> str:
    """数字格式化：4800 → '4.8k'，<1000 原样。"""
    if n is None:
        return "0"
    try:
        num: float = float(n)
    except (ValueError, TypeError):
        return str(n)
    if num >= 1000:
        result: str = f"{num / 1000:.1f}"
        if result.endswith(".0"):
            result = result[:-2]
        return f"{result}k"
    return str(int(num))
