"""display builder 本地化回归 — 防「加语言漏配汇率/货币」踩坑（2026-09-01 ru 事故复盘）。

加新语言时若 _make_money() 或 Config.FX_* 漏配，非 zh 语言价格会保持 CNY 原值；
本文件断言任意非 zh 语言 build_display 输出价格已按 per_cny 换算。
对应 docs/加语言checklist.md 三层防线中的「机器强制」层。
"""

from domain.display.builder import _fmt_dim_num, build_display

# 高质商品 mapped（结构可过 evaluate_product/evaluate_supplier）
_MAPPED = {
    "priceCNY": {"low": 5.0, "high": 6.0}, "moq": 50, "sold": 2000,
    "repurchase": 40.0, "positive_rate": 98.0, "wantBuy": 200,
    "return7day": "OK", "has_service_labels": True, "unit": "件",
    "factoryFlags": "超级工厂", "sellerType": "super_factory",
    "certType": "SGS 实地认证", "shop_years": 5,
    "title": "测试商品", "supplierName": "测试供应商",
}


def test_non_zh_price_converted_by_money():
    """ru：price 必须按 per_cny 换算（≠ CNY 原值）。漏配汇率时此测试红。"""
    money = {"symbol": "₽", "per_cny": 13.19, "decimals": 0}
    d = build_display(_MAPPED, "ru", money)
    assert d["price"]["low"] == round(5.0 * 13.19, 6)
    assert d["price"]["high"] == round(6.0 * 13.19, 6)
    assert d["price"]["low"] != 5.0  # 没换算 = 仍 CNY


def test_no_money_keeps_cny():
    """money=None（zh/模板路径）：价格保持 CNY 原值。"""
    d = build_display(_MAPPED, "zh")
    assert d["price"]["low"] == 5.0
    assert d["price"]["high"] == 6.0


def test_fmt_dim_num_ru_thousand_sep():
    """ru 千分位用空格、小数用逗号；en 保持逗号千分位。"""
    assert _fmt_dim_num(8900, "ru") == "8 900"
    assert _fmt_dim_num(67.5, "ru") == "67,5"


def test_nonzh_machine_fields_no_cjk_gate():
    """批C 出口闸：非 zh 的工厂透传中文（认证/徽章/发货地/specs）不得发给前端；zh 保留原样。"""
    from utils.i18n_core import cjk_in
    mapped = dict(_MAPPED)
    mapped.update({
        "shippingLocation": "浙江 义乌",
        "specs": [{"name": "材质", "value": "ABS"}, {"name": "Type", "value": "LED"}],
    })
    for lang in ("en", "ru", "vi", "th"):
        d = build_display(mapped, lang, {"symbol": "$", "per_cny": 0.14, "decimals": 2})
        f = d["factory"]
        for field in ("certType", "factoryFlags", "shippingLocation"):
            assert not cjk_in(str(f.get(field, ""))), f"{lang} factory.{field} 漏中文: {f.get(field)!r}"
        assert not any(cjk_in(str(s.get("name", ""))) or cjk_in(str(s.get("value", "")))
                       for s in d["specs"]), f"{lang} specs 漏中文"
    d_zh = build_display(mapped, "zh")
    assert d_zh["factory"]["certType"] == "SGS 实地认证"
    assert d_zh["factory"]["shippingLocation"] == "浙江 义乌"
    assert d_zh["specs"] and d_zh["specs"][0]["name"] == "材质"
    assert _fmt_dim_num(8900, "en") == "8,900"
    assert _fmt_dim_num(8900, "") == "8,900"


def test_price_usd_when_money_injects_usd_factor():
    """拿样美元价：money 带 usd_per_cny → price.usd = CNY × 系数；不带则不输出。"""
    money = {"symbol": "₽", "per_cny": 13.19, "decimals": 0, "usd_per_cny": 0.149254}
    d = build_display(_MAPPED, "ru", money)
    assert d["price"]["usd"]["low"] == round(5.0 * 0.149254, 6)
    assert d["price"]["usd"]["high"] == round(6.0 * 0.149254, 6)

    d_none = build_display(_MAPPED, "ru", {"symbol": "₽", "per_cny": 13.19, "decimals": 0})
    assert "usd" not in d_none["price"]
    d_zh = build_display(_MAPPED, "zh")  # 纯模板调用（money=None）
    assert "usd" not in d_zh["price"]
