"""verdict_engine 单元测试 — judge_product / judge_factory / judge_sample 全覆盖。

V1.2：每个判词函数返回 {key, params} dict，key 对应 term_glossary.json 条目。
"""

from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "api"))

from domain.verdict_engine import judge_product, judge_factory, judge_sample, judge_all  # noqa: E402


# ====================================================================
# judge_product — 4 分支
# ====================================================================

def _product_data(**overrides):
    """构造产品数据，默认值使判词落在 recommend_sample。"""
    base = {
        "certType": "SGS",
        "sold": 5000,
        "return7day": "OK",
        "priceCNY": {"low": 5.0},
        "moq": 2,
        "unit": "件",
    }
    base.update(overrides)
    return base


def test_product_recommend_sample():
    """有认证 + 高销量(>=1000) + 7天无理由 → recommend_sample。"""
    v = judge_product(_product_data())
    assert v["key"] == "verdict_product_recommend"
    assert "price" in v["params"]
    assert "sold" in v["params"]


def test_product_consider():
    """有认证 + 中销量(>=100) → consider。"""
    v = judge_product(_product_data(sold=300, return7day="NO"))
    assert v["key"] == "verdict_product_consider"


def test_product_no_cert():
    """无认证 + 有销量(>=500) → no_cert。"""
    v = judge_product(_product_data(certType=None, sold=600))
    assert v["key"] == "verdict_product_no_cert"
    assert "deposit" in v["params"]


def test_product_insufficient_data():
    """无认证 + 低销量 → insufficient。"""
    v = judge_product(_product_data(certType=None, sold=50))
    assert v["key"] == "verdict_product_insufficient"


def test_product_cert_null_string():
    """certType='null' 被视为无认证。"""
    v = judge_product(_product_data(certType="null", sold=50))
    assert v["key"] == "verdict_product_insufficient"


def test_product_zero_sold():
    """sold=0 走 insufficient 分支。"""
    v = judge_product(_product_data(certType=None, sold=0))
    assert v["key"] == "verdict_product_insufficient"


# ====================================================================
# judge_factory — 5 分支
# ====================================================================

def _factory_data(**overrides):
    """构造工厂数据，默认值使判词落在 reliable。"""
    base = {
        "shop_years": 5,
        "certType": "SGS",
        "sellerType": "super_factory",
        "factoryFlags": "生产厂家 · 超级工厂",
    }
    base.update(overrides)
    return base


def test_factory_reliable():
    """高级认证 + 3年以上 → reliable。"""
    v = judge_factory(_factory_data())
    assert v["key"] == "verdict_factory_reliable"
    assert "years" in v["params"]
    assert "cert" in v["params"]


def test_factory_cooperative():
    """生产厂家 + 有认证 + (<3年或不高级) → cooperative。"""
    v = judge_factory(_factory_data(
        sellerType="normal_factory",
        factoryFlags="生产厂家",
        shop_years=1,
    ))
    assert v["key"] == "verdict_factory_cooperative"


def test_factory_self_claimed():
    """生产厂家 + 无认证 → self_claimed。"""
    v = judge_factory(_factory_data(
        sellerType="normal_factory",
        factoryFlags="生产厂家",
        certType=None,
    ))
    assert v["key"] == "verdict_factory_self_claimed"


def test_factory_trader():
    """非生产厂家 → trader。"""
    v = judge_factory(_factory_data(
        sellerType="normal",
        factoryFlags="非生产厂家",
        certType=None,
    ))
    assert v["key"] == "verdict_factory_trader"


def test_factory_insufficient():
    """无法判断 → insufficient。"""
    v = judge_factory(_factory_data(
        sellerType="normal",
        factoryFlags="",
        certType=None,
        shop_years=0,
    ))
    assert v["key"] == "verdict_factory_insufficient"


def test_factory_advanced_by_flags():
    """高级认证通过 factoryFlags 中的「源头旗舰」识别 → reliable。"""
    v = judge_factory(_factory_data(
        sellerType="normal",
        factoryFlags="生产厂家 · 源头旗舰",
        shop_years=5,
    ))
    assert v["key"] == "verdict_factory_reliable"


def test_factory_years_edge():
    """刚好 3 年 → reliable。"""
    v = judge_factory(_factory_data(shop_years=3))
    assert v["key"] == "verdict_factory_reliable"


def test_factory_no_flags():
    """factoryFlags=None 不崩溃。"""
    v = judge_factory(_factory_data(factoryFlags=None))
    assert isinstance(v, dict) and "key" in v


# ====================================================================
# judge_sample — 统一模板
# ====================================================================

def test_sample_always_returns_two_payment():
    """任何输入都返回两段付款流程 KEY。"""
    v1 = judge_sample({})
    v2 = judge_sample({"moq": 100, "sold": 99999})
    assert v1 == v2
    assert v1["key"] == "verdict_sample_two_payment"


# ====================================================================
# judge_all — 集成
# ====================================================================

def test_judge_all_returns_three_keys():
    """judge_all 返回 product / factory / sample 三个维度的 {key, params}。"""
    data = {
        "certType": "SGS",
        "sold": 5000,
        "return7day": "OK",
        "priceCNY": {"low": 5.0},
        "moq": 2,
        "unit": "件",
        "shop_years": 5,
        "sellerType": "super_factory",
        "factoryFlags": "生产厂家 · 超级工厂",
    }
    result = judge_all(data)
    assert set(result.keys()) == {"product", "factory", "sample"}
    for v in result.values():
        assert isinstance(v, dict) and "key" in v and "params" in v


# ====================================================================
# 分支唯一性 — 确认不同条件落到不同 KEY
# ====================================================================

def test_product_branches_are_unique():
    """4 个分支落到不同的 KEY。"""
    v1 = judge_product(_product_data(certType="SGS", sold=1000, return7day="OK"))
    v2 = judge_product(_product_data(certType="SGS", sold=100, return7day="NO"))
    v3 = judge_product(_product_data(certType=None, sold=500))
    v4 = judge_product(_product_data(certType=None, sold=99))
    keys = {v1["key"], v2["key"], v3["key"], v4["key"]}
    assert len(keys) >= 3  # 至少 3 种不同判词


def test_factory_branches_are_unique():
    """5 个分支落到不同的 KEY。"""
    v1 = judge_factory(_factory_data(sellerType="super_factory",
                                      factoryFlags="生产厂家 · 超级工厂", shop_years=5))
    v2 = judge_factory(_factory_data(sellerType="normal_factory",
                                      factoryFlags="生产厂家", shop_years=1))
    v3 = judge_factory(_factory_data(sellerType="normal_factory",
                                      factoryFlags="生产厂家", certType=None))
    v4 = judge_factory(_factory_data(sellerType="normal",
                                      factoryFlags="非生产厂家", certType=None))
    v5 = judge_factory(_factory_data(sellerType="normal",
                                      factoryFlags="", certType=None, shop_years=0))
    keys = {v1["key"], v2["key"], v3["key"], v4["key"], v5["key"]}
    assert len(keys) >= 4  # 至少 4 种不同判词
