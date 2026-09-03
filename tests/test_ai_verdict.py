"""domain/display/ai_verdict 测试 — pack_ai_input 的 no-data 维度裁剪（N6）。

测行为不测实现：低质商品（维度无数据）的 AI 输入不应包含 no-data 维度，
高质商品（维度有数据）应全保留，中间态只保留有数据的维度。
"""

from domain.display.ai_verdict import pack_ai_input
from domain.evaluate import evaluate_product, evaluate_supplier, evaluate_summary


def _pack(mapped: dict) -> dict:
    p = evaluate_product(mapped)
    s = evaluate_supplier(mapped)
    sm = evaluate_summary(p, s)
    return pack_ai_input(p, s, sm, mapped, "en")


def test_no_data_dims_trimmed_from_low_quality_product():
    """黑箱低质商品：9 个维度全 no-data → dimensions 应为空，不浪费 token。"""
    mapped = {
        "priceCNY": {"low": 0, "high": 0}, "moq": None, "sold": None,
        "repurchase": None, "positive_rate": None, "wantBuy": None,
        "return7day": "", "has_service_labels": False, "unit": "",
        "factoryFlags": "", "sellerType": "",
        "certType": None, "shop_years": None,
        "title": "t", "supplierName": "s",
    }
    ai = _pack(mapped)
    assert ai["dimensions"]["product"] == []
    assert ai["dimensions"]["supplier"] == []


def test_high_quality_product_keeps_all_dims():
    """高质商品：产品 4 维 + 供应商 5 维全有数据 → 全保留。"""
    mapped = {
        "priceCNY": {"low": 5.0, "high": 6.0}, "moq": 50, "sold": 2000,
        "repurchase": 40.0, "positive_rate": 98.0, "wantBuy": 200,
        "return7day": "OK", "has_service_labels": True, "unit": "件",
        "factoryFlags": "超级工厂", "sellerType": "super_factory",
        "certType": "SGS 实地认证", "shop_years": 5,
        "title": "t", "supplierName": "s",
    }
    ai = _pack(mapped)
    assert len(ai["dimensions"]["product"]) == 4
    assert len(ai["dimensions"]["supplier"]) == 5


def test_partial_data_keeps_only_available_dims():
    """中间态：只保留有数据的维度，且保留维度 data 非空。"""
    mapped = {
        "priceCNY": {"low": 3.0, "high": 4.0}, "moq": 100, "sold": 1500,
        "repurchase": None, "positive_rate": None, "wantBuy": None,
        "return7day": "OK", "has_service_labels": True, "unit": "件",
        "factoryFlags": "源头工厂", "sellerType": "",
        "certType": None, "shop_years": None,
        "title": "t", "supplierName": "s",
    }
    ai = _pack(mapped)
    pkeys = {d["key"] for d in ai["dimensions"]["product"]}
    skeys = {d["key"] for d in ai["dimensions"]["supplier"]}
    assert pkeys == {"d1", "d3", "d6"}  # v2 产品仅 d1/d3/d5/d6 四维：wantBuy 空 → d5(关注) 被裁
    assert skeys == {"d1"}  # v2 供应商五维：认证/年限/复购/好评全空 → d2/d3/d4/d5 被裁
    for sec in ("product", "supplier"):
        for d in ai["dimensions"][sec]:
            assert d["data"] not in ("", "no data")
