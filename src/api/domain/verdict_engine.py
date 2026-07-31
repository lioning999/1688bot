"""V1.2 规则引擎 — 输出 KEY + 参数字典，不再输出中文字符串。

判词文案统一从 term_glossary.json 查表（4 语言预翻译）。
前端由 display JSON 中的 verdictProduct / verdictFactory / verdictSample 直接展示。
"""

from typing import Any


# ====================================================================
# 数字格式化（语言无关，4.8k / 1.2k 等）
# ====================================================================

def _fmt_k(n: Any) -> str:
    """4800 → '4.8k'，<1000 原样。"""
    try:
        num: float = float(n) if n else 0
    except (ValueError, TypeError):
        return str(n)
    if num >= 1000:
        result: str = f"{num / 1000:.1f}"
        if result.endswith(".0"):
            result = result[:-2]
        return f"{result}k"
    return str(int(num))


# ====================================================================
# 判词生成
# ====================================================================

def _verdict(key: str, **params: Any) -> dict[str, Any]:
    """构建判词输出：{key, params} dict。"""
    return {"key": key, "params": params}


def judge_product(data: dict[str, Any]) -> dict[str, Any]:
    """产品判词：根据 cert + sold + return7day 分支。

    返回 {key, params}，key 对应 term_glossary.json 中的 verdict_product_* 条目。
    """
    cert: Any = data.get("certType")
    sold: Any = data.get("sold", 0)
    return_ok: bool = data.get("return7day") == "OK"

    price_cny_raw: Any = data.get("priceCNY") or {}
    price_cny: dict[str, Any] = price_cny_raw if isinstance(price_cny_raw, dict) else {}  # type: ignore[assignment]
    price: Any = price_cny.get("low", 0)
    moq: Any = data.get("moq", 2)
    unit: str = str(data.get("unit", "件"))

    try:
        deposit: int = int(float(price) * int(moq) + 10)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        deposit = 10

    has_cert: bool = bool(cert and cert != "null")
    sold_str: str = _fmt_k(sold)

    if has_cert and sold >= 1000 and return_ok:
        return _verdict("verdict_product_recommend",
                        price=str(price), moq=str(moq), unit=unit, sold=sold_str)
    if has_cert and sold >= 100:
        return _verdict("verdict_product_consider",
                        price=str(price), moq=str(moq), unit=unit, sold=sold_str)
    if not has_cert and sold >= 500:
        return _verdict("verdict_product_no_cert",
                        sold=sold_str, deposit=str(deposit))
    return _verdict("verdict_product_insufficient",
                    deposit=str(deposit))


def judge_factory(data: dict[str, Any]) -> dict[str, Any]:
    """工厂判词：根据 years + cert + flags 分支。

    返回 {key, params}，key 对应 term_glossary.json 中的 verdict_factory_* 条目。
    """
    years: Any = data.get("shop_years", 0) or 0
    cert: Any = data.get("certType")
    has_cert: bool = bool(cert and cert != "null")
    cert_name: str = str(cert).upper() if has_cert else ""

    flags: str = str(data.get("factoryFlags", "")) if data.get("factoryFlags") else ""
    seller_type: str = str(data.get("sellerType", ""))

    # 高级认证（超级工厂 / 源头旗舰 / 实力工厂）
    is_advanced: bool = (
        seller_type in ("super_factory", "flagship")
        or any(kw in flags for kw in ("超级工厂", "源头旗舰", "实力工厂"))
    )
    # 生产厂家
    is_factory: bool = (
        "非生产厂家" not in flags
        and ("生产厂家" in flags or seller_type in ("normal_factory", "super_factory"))
    )
    # 贸易商
    is_trader: bool = "非生产厂家" in flags

    if is_advanced and years >= 3:
        return _verdict("verdict_factory_reliable", years=str(years), cert=cert_name)
    if is_factory and has_cert:
        return _verdict("verdict_factory_cooperative", years=str(years))
    if is_factory and not has_cert:
        return _verdict("verdict_factory_self_claimed")
    if is_trader:
        return _verdict("verdict_factory_trader")
    return _verdict("verdict_factory_insufficient")


def judge_sample(data: dict[str, Any]) -> dict[str, Any]:
    """拿样判词 — 统一两段付款流程。"""
    return _verdict("verdict_sample_two_payment")


def judge_all(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """一次调用返回三个维度的判词。

    Returns:
        {"product": {key, params}, "factory": {key, params}, "sample": {key, params}}
        每个 dict 的 key 对应 term_glossary.json 中的条目。
    """
    return {
        "product": judge_product(data),
        "factory": judge_factory(data),
        "sample":  judge_sample(data),
    }
