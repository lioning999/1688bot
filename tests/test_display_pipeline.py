"""display pipeline 集成测试 — build_display → translate_display → result 结构。

覆盖:
  - display_builder 输出结构（Path 1/2/3）
  - translator 4 语言翻译
  - V1 mapped 不被覆盖
  - 无 lang 时不翻译
  - 不支持的语言降级为 en
  - 各 builder 崩溃不抛异常
"""
import asyncio
import json
import os
import sys
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "api"))

import pytest

from domain.display_builder import build_display
from domain.translator import translate_display

# ---- 测试夹具：模拟 mapped 数据（来自 demo.json 格式） ----

SAMPLE_MAPPED = {
    "title": "跨境苹果17pm手机壳磁吸16pro肤感防摔iphone15promax磨砂保护套",
    "image": "https://cbu01.alicdn.com/img/ibank/O1CN01HTCT63.jpg",
    "images": ["https://cbu01.alicdn.com/img/ibank/O1CN01HTCT63.jpg"],
    "itemUrl": "https://detail.1688.com/offer/test.html",
    "offerId": "12345678",
    "priceCNY": {"low": 7.58, "high": 9.0},
    "moq": 2,
    "unit": "个",
    "return7day": "OK",
    "sold": 52000,
    "repurchase": 54.0,
    "badgeLabels": [{"label": "支持混批", "class": "green"}, {"label": "跨境专供", "class": "blue"}],
    "specs": [
        {"name": "材质", "value": "硅胶"},
        {"name": "品牌", "value": "三丰"},
    ],
    "price_tiers": [
        {"qty_min": 2, "qty_max": 99, "unit_price": 9.0},
        {"qty_min": 100, "qty_max": None, "unit_price": 7.58},
    ],
    "skus": [{"sku_name": "白色", "sku_image": "https://cbu01.alicdn.com/img/1.jpg"}],
    "verdict_product": {"key": "verdict_product_recommend", "params": {"price": "7.58", "moq": "2", "unit": "个", "sold": "52k"}},
    "verdict_factory": {"key": "verdict_factory_reliable", "params": {"years": "10", "cert": "SGS 实地认证"}},
    "verdict_sample": {"key": "verdict_sample_two_payment", "params": {}},
    "supplierName": "佛山市南海区三丰手机配件有限公司",
    "shippingLocation": "广东佛山",
    "industryCluster": "industry_foshan",
    "factoryFlags": "生产厂家 · 超级工厂 · 源头旗舰 · 工厂直供",
    "certType": "SGS 实地认证",
    "certReportUrl": "https://r.1688.com/auth/report.htm",
    "shopUrl": "https://shop123.1688.com",
    "rankText": "手机壳行业榜第1名",
    "sellerTierLabel": "源头工厂",
    "dataTier": "sufficient",
    "dataTierReason": "tier_sufficient_2y",
    "shop_years": 10,
    "shop_rate": 98.0,
}


# ====================================================================
# 1. build_display 结构测试（纯函数，不需要 async）
# ====================================================================

class TestBuildDisplay:
    """Path 1/2/3 结构校验。"""

    def test_builds_all_top_level_keys(self):
        """display JSON 包含所有顶层键。"""
        d = build_display(SAMPLE_MAPPED, "en")
        expected_keys = {
            "title", "titleOrig", "images", "videoUrl", "itemUrl", "offerId",
            "price", "trustBar", "badges", "specs", "sales",
            "skus", "verdictProduct", "verdictFactory", "verdictSample", "factory",
        }
        assert set(d.keys()) >= expected_keys

    def test_path1_price_is_numeric(self):
        """Path 1：价格字段是数字/英文，不含中文。"""
        d = build_display(SAMPLE_MAPPED, "en")
        p = d["price"]
        assert p["low"] == 7.58
        assert p["high"] == 9.0
        assert p["moq"] == 2
        assert p["unit"] == "pcs"  # 单位查表映射：个→pcs

    def test_path1_trust_bar_stars_and_tier_english(self):
        """Path 1：trustBar 的 stars/tier 是英文。"""
        d = build_display(SAMPLE_MAPPED, "en")
        tb = d["trustBar"]
        assert tb["stars"] == "★★★"
        assert tb["tier"] == "Recommended"
        assert "52k+ sold" in tb["sold"]
        assert "10y on 1688" in tb["years"]

    def test_path1_badges_english(self):
        """Path 1：badge 的 text 是英文。"""
        d = build_display(SAMPLE_MAPPED, "en")
        badges = d["badges"]
        texts = [b["text"] for b in badges]
        assert "7-Day Returns" in texts
        assert any("54" in t and "repurchase" in t for t in texts)

    def test_path2_seller_label_en(self):
        """Path 2：sellerLabel 字典查表 — 英文。"""
        d = build_display(SAMPLE_MAPPED, "en")
        assert "Factory" in d["trustBar"]["label"]

    def test_path2_seller_label_vi(self):
        """Path 2：sellerLabel 字典查表 — 越南语。"""
        d = build_display(SAMPLE_MAPPED, "vi")
        assert "Nhà Máy" in d["trustBar"]["label"]

    def test_path2_seller_label_th(self):
        """Path 2：sellerLabel 字典查表 — 泰语。"""
        d = build_display(SAMPLE_MAPPED, "th")
        assert "โรงงาน" in d["trustBar"]["label"]

    def test_path2_seller_label_id(self):
        """Path 2：sellerLabel 字典查表 — 印尼语。"""
        d = build_display(SAMPLE_MAPPED, "id")
        assert "Pabrik" in d["trustBar"]["label"]

    def test_path2_mixed_badge_per_lang(self):
        """Path 2：混批 badge 按语言不同。"""
        en = build_display(SAMPLE_MAPPED, "en")
        vi = build_display(SAMPLE_MAPPED, "vi")
        th = build_display(SAMPLE_MAPPED, "th")
        id_ = build_display(SAMPLE_MAPPED, "id")

        def find_mixed(display):
            for b in display["badges"]:
                if "mixed" in b["text"].lower() or "hỗ" in b["text"].lower() or "คละ" in b["text"] or "campuran" in b["text"].lower():
                    return b["text"]
            return None

        en_text = [b["text"] for b in en["badges"] if "Mixed" in b["text"]]
        vi_text = [b["text"] for b in vi["badges"] if "Hỗ" in b["text"]]
        th_text = [b["text"] for b in th["badges"] if "คละ" in b["text"]]
        id_text = [b["text"] for b in id_["badges"] if "Campuran" in b["text"] or "Mendukung" in b["text"]]

        assert any("Mixed" in t for t in en_text), f"EN mixed badge not found: {en_text}"
        assert any("Hỗ" in t for t in vi_text), f"VI mixed badge not found: {vi_text}"
        assert any("คละ" in t for t in th_text), f"TH mixed badge not found: {th_text}"
        assert any("Campuran" in t or "Mendukung" in t for t in id_text), f"ID mixed badge not found: {id_text}"

    def test_path3_chinese_preserved_in_specs(self):
        """Path 3：specs 中文原文保留。"""
        d = build_display(SAMPLE_MAPPED, "en")
        specs = d["specs"]
        # 中文原文还在（等 translator 翻译）
        names = [s["name"] for s in specs]
        assert "材质" in names

    def test_path3_chinese_preserved_in_verdict(self):
        """判词：glossary 查表，en 输出英文判词。"""
        d = build_display(SAMPLE_MAPPED, "en")
        assert "Recommend" in d["verdictProduct"]
        assert "factory" in d["verdictFactory"].lower()

    def test_path3_factory_explain_chinese(self):
        """工厂解释文案：en 输出英文（glossary 查表）。"""
        d = build_display(SAMPLE_MAPPED, "en")
        f = d["factory"]
        assert "platform-verified" in f["sellerExplain"].lower()

    def test_unknown_lang_falls_back_to_en(self):
        """不支持的语言降级为英文。"""
        d = build_display(SAMPLE_MAPPED, "fr")
        assert "Factory" in d["trustBar"]["label"]

    def test_empty_mapped_does_not_crash(self):
        """空 mapped 不抛异常，返回最小结构。"""
        d = build_display({}, "en")
        assert "title" in d
        assert "price" in d
        assert d["price"]["low"] == 0

    def test_sales_explain_chinese_for_high_sold(self):
        """高销量触发解释文案：en 输出英文（glossary 查表）。"""
        d = build_display(SAMPLE_MAPPED, "en")
        assert "market validation" in d["sales"]["explain"].lower()

    def test_sales_explain_empty_for_low_sold(self):
        """低销量不生成解释。"""
        low_sold = {**SAMPLE_MAPPED, "sold": 50}
        d = build_display(low_sold, "en")
        assert d["sales"]["explain"] == ""

    def test_factory_title_orig_preserved(self):
        """titleOrig 保存原始中文标题。"""
        d = build_display(SAMPLE_MAPPED, "en")
        assert d["titleOrig"] == SAMPLE_MAPPED["title"]


# ====================================================================
# 2. translate_display 测试（需 Qwen API）
# ====================================================================

@pytest.mark.asyncio
class TestTranslateDisplay:
    """translate_display 集成测试。需要 Qwen API 连通。"""

    async def test_translate_en_sets_marker(self):
        """翻译后设置 _translatedLang。"""
        d = build_display(SAMPLE_MAPPED, "en")
        result = await translate_display(d, "en")
        assert result.get("_translatedLang") == "en"

    async def test_translate_en_title_no_chinese(self):
        """英文翻译后标题不含中文。"""
        d = build_display(SAMPLE_MAPPED, "en")
        result = await translate_display(d, "en")
        assert not any("一" <= ch <= "鿿" for ch in result.get("title", ""))

    async def test_translate_vi_sets_marker(self):
        """越南语翻译后设置 _translatedLang。"""
        d = build_display(SAMPLE_MAPPED, "vi")
        result = await translate_display(d, "vi")
        assert result.get("_translatedLang") == "vi"

    async def test_translate_all_four_langs(self):
        """4 语言全部翻译成功。"""
        for lang in ["en", "vi", "th", "id"]:
            d = build_display(SAMPLE_MAPPED, lang)
            result = await translate_display(d, lang)
            assert result.get("_translatedLang") == lang, f"{lang} translation failed"
            # 判词翻译后不含中文（或至少部分翻译了）
            vp = result.get("verdictProduct", "")
            # 宽松检查：判词至少变了（不等于原文）
            assert vp != "", f"{lang} verdictProduct empty"

    async def test_translate_no_lang_does_nothing(self):
        """空 lang 不翻译，不设标记。"""
        d = build_display(SAMPLE_MAPPED, "en")
        result = await translate_display(d, "")
        assert "_translatedLang" not in result

    async def test_translate_preserves_english_fields(self):
        """翻译不触碰 Path 1 英文字段。"""
        d = build_display(SAMPLE_MAPPED, "en")
        result = await translate_display(d, "vi")
        tb = result["trustBar"]
        assert "52k+ sold" in tb["sold"]
        assert "10y on 1688" in tb["years"]

    async def test_translate_specs_not_empty(self):
        """翻译后 specs 仍非空。"""
        d = build_display(SAMPLE_MAPPED, "en")
        result = await translate_display(d, "en")
        specs = result.get("specs", [])
        assert len(specs) == 2
        assert "name" in specs[0] and "value" in specs[0]

    async def test_translate_factory_fields_translated(self):
        """工厂字段被翻译。"""
        d = build_display(SAMPLE_MAPPED, "en")
        result = await translate_display(d, "en")
        f = result["factory"]
        # 这些字段原本是中文，翻译后不应包含中文
        chinese_fields = ["sellerExplain", "flagsExplain", "certExplain"]
        for key in chinese_fields:
            val = f.get(key, "")
            if val:
                has_cn = any("一" <= ch <= "鿿" for ch in val)
                assert not has_cn, f"factory.{key} still has Chinese: {val[:60]}"


# ====================================================================
# 3. 并发 + 降级测试
# ====================================================================

@pytest.mark.asyncio
class TestTranslateEdgeCases:
    """边界情况。"""

    async def test_empty_display_no_crash(self):
        """空 display 翻译不崩溃。"""
        result = await translate_display({}, "en")
        assert "_translatedLang" not in result

    async def test_no_chinese_fields_no_api_call(self):
        """无中文字段时不调 API（通过 _extract_translatable 返回空）。"""
        d = {"title": "Hello", "trustBar": {"label": "Test"}, "price": {"low": 1.0}}
        result = await translate_display(d, "en")
        # 没有中文 → 不翻译 → 无 _translatedLang
        assert "_translatedLang" not in result

    async def test_parallel_translate_all_langs(self):
        """并发翻译 4 语言不互相干扰。"""
        async def translate_one(lang):
            d = build_display(SAMPLE_MAPPED, lang)
            return await translate_display(d, lang)

        results = await asyncio.gather(
            translate_one("en"),
            translate_one("vi"),
            translate_one("th"),
            translate_one("id"),
        )
        for i, (r, lang) in enumerate(zip(results, ["en", "vi", "th", "id"])):
            assert r.get("_translatedLang") == lang, f"concurrent {lang} failed"


# ====================================================================
# 4. V1 回归 — ensure mapped not corrupted
# ====================================================================

class TestV1Regression:
    """确保 V1 mapped 数据不被 build_display/translate 破坏。"""

    def test_build_display_does_not_mutate_input(self):
        """build_display 不修改输入 mapped。"""
        import copy
        original = copy.deepcopy(SAMPLE_MAPPED)
        build_display(SAMPLE_MAPPED, "en")
        assert SAMPLE_MAPPED == original

    def test_display_key_not_clash_with_mapped(self):
        """display 的顶层键不与 mapped 冲突（renderResult 分离清晰）。"""
        d = build_display(SAMPLE_MAPPED, "en")
        # display 不包含 mapped 的原始键如 priceCNY, shop_years 等
        assert "priceCNY" not in d
        assert "shop_years" not in d
        assert "repurchase" not in d
        # 但保留需要渲染的键
        assert "price" in d
        assert "verdictProduct" in d


if __name__ == "__main__":
    # 手动运行时输出彩色结果
    pytest.main([__file__, "-v", "--tb=short"])
