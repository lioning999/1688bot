"""analyze_svc 集成测试 — build_result_with_display + display cache。

覆盖:
  - V1 mapped 始终在 result 中（底线不丢）
  - lang="" 时 build_display 但不翻译
  - lang="en" 时 build + translate
  - display cache 命中/未命中
  - 缓存过期
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "api"))

import pytest

# 测试用 mapped 数据
TEST_MAPPED = {
    "title": "韩版不锈钢项链女 ins风锁骨链不掉色",
    "image": "https://cbu01.alicdn.com/img/ibank/test.jpg",
    "images": ["https://cbu01.alicdn.com/img/ibank/test.jpg"],
    "itemUrl": "https://detail.1688.com/offer/test.html",
    "offerId": "99999999",
    "priceCNY": {"low": 1.4, "high": 2.5},
    "moq": 3,
    "unit": "件",
    "return7day": "OK",
    "sold": 4892,
    "repurchase": 42.0,
    "badgeLabels": [{"label": "支持混批", "class": "green"}],
    "specs": [
        {"name": "材质", "value": "不锈钢"},
        {"name": "款式", "value": "锁骨链"},
    ],
    "price_tiers": [{"qty_min": 3, "qty_max": 99, "unit_price": 1.4}],
    "skus": [],
    "verdict_product": "✅ 推荐拿样 — 进价 ¥1.4、3件起批、月销 4.8k+，试错成本极低",
    "verdict_factory": "✅ 工厂可靠 — 6年老店+SGS验厂，合作风险低",
    "verdict_sample": "① 付定金 → ② 验货照片 → ③ 付尾款 → ④ 发货",
    "supplierName": "义乌市雨灏贸易有限公司",
    "shippingLocation": "浙江省金华市义乌市",
    "industryCluster": "饰品产业带",
    "factoryFlags": "超级工厂 · 深度验厂",
    "certType": "SGS 实地认证",
    "certReportUrl": "",
    "shopUrl": "",
    "rankText": "",
    "sellerTierLabel": "源头工厂",
    "dataTier": "sufficient",
    "dataTierReason": "官方认证 + 经营 2 年以上",
    "shop_years": 6,
    "shop_rate": 97.0,
}


# 直接 import build_result_with_display 函数
from services.analyze_svc import build_result_with_display, _display_cache_get, _display_cache_set
from services.analyze_svc import _display_cache


@pytest.fixture(autouse=True)
def clear_display_cache():
    """每个测试前清 display 缓存。"""
    _display_cache.clear()
    yield


@pytest.mark.asyncio
class TestBuildResultWithDisplay:
    """build_result_with_display 核心逻辑。"""

    async def test_result_always_has_mapped_fields(self):
        """V1 mapped 字段始终在 result 中。"""
        result = await build_result_with_display(TEST_MAPPED, "99999999", "")
        for key in ["title", "priceCNY", "specs", "moq", "unit",
                     "verdict_product", "verdict_factory", "verdict_sample"]:
            assert key in result, f"V1 key '{key}' missing from result"

    async def test_result_always_has_display(self):
        """无论有没有 lang，result 都含 display。"""
        for lang in ["", "en", "vi"]:
            result = await build_result_with_display(TEST_MAPPED, "99999999", lang)
            assert "display" in result, f"display missing for lang='{lang}'"
            assert isinstance(result["display"], dict)

    async def test_no_lang_display_not_translated(self):
        """lang="" 时 display 含中文原文（未翻译）。"""
        result = await build_result_with_display(TEST_MAPPED, "99999999", "")
        d = result["display"]
        # specs 还是中文
        has_cn = any("一" <= ch <= "鿿" for ch in json.dumps(d["specs"], ensure_ascii=False))
        assert has_cn, "specs should still be Chinese when lang=''"
        # 没有翻译标记
        assert "_translatedLang" not in d

    async def test_with_lang_display_translated(self):
        """lang="en" 时 display 被翻译。"""
        result = await build_result_with_display(TEST_MAPPED, "99999999", "en")
        d = result["display"]
        assert d.get("_translatedLang") == "en"

    async def test_display_cache_hit_skips_translation(self):
        """display 缓存命中后直接返回，不重复调 API。"""
        result1 = await build_result_with_display(TEST_MAPPED, "99999999", "en")
        t1 = result1["display"].get("_translatedLang")

        # 第二次调用同 offer_id + lang（缓存命中）
        result2 = await build_result_with_display(TEST_MAPPED, "99999999", "en")
        t2 = result2["display"].get("_translatedLang")

        assert t1 == "en"
        assert t2 == "en"
        # 缓存命中时直接返回，两个 display 应该是同一个对象（引用相等）
        assert result1["display"] is result2["display"]

    async def test_different_lang_different_cache(self):
        """不同语言用不同缓存键。"""
        result_en = await build_result_with_display(TEST_MAPPED, "99999999", "en")
        result_vi = await build_result_with_display(TEST_MAPPED, "99999999", "vi")

        assert result_en["display"]["_translatedLang"] == "en"
        assert result_vi["display"]["_translatedLang"] == "vi"
        # 两个 display 内容不同（不同语言翻译）
        assert result_en["display"] is not result_vi["display"]

    async def test_display_structure_complete(self):
        """display 包含所有必需字段。"""
        result = await build_result_with_display(TEST_MAPPED, "99999999", "en")
        d = result["display"]
        required = ["title", "titleOrig", "price", "trustBar", "badges",
                     "specs", "sales", "skus",
                     "verdictProduct", "verdictFactory", "verdictSample", "factory"]
        for key in required:
            assert key in d, f"display missing key: {key}"


class TestDisplayCache:
    """_display_cache_get/set 助手函数。"""

    def test_cache_set_and_get(self):
        """基本 set/get 流程。"""
        _display_cache_set("12345", "en", {"title": "Hello"})
        result = _display_cache_get("12345", "en")
        assert result == {"title": "Hello"}

    def test_cache_miss_returns_none(self):
        """未命中返回 None。"""
        result = _display_cache_get("nonexistent", "en")
        assert result is None

    def test_cache_different_key(self):
        """不同 key 不互相干扰。"""
        _display_cache_set("a", "en", {"x": 1})
        _display_cache_set("a", "vi", {"x": 2})
        _display_cache_set("b", "en", {"x": 3})
        assert _display_cache_get("a", "en") == {"x": 1}
        assert _display_cache_get("a", "vi") == {"x": 2}
        assert _display_cache_get("b", "en") == {"x": 3}

    def test_cache_expired_returns_none(self):
        """过期缓存返回 None。"""
        # 手动注入过期条目
        key = "expired:en"
        from services.analyze_svc import _display_cache, _DISPLAY_CACHE_TTL
        _display_cache[key] = (time.time() - _DISPLAY_CACHE_TTL - 1, {"old": True})
        result = _display_cache_get("expired", "en")
        assert result is None
        # 过期条目被清理
        assert key not in _display_cache


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
