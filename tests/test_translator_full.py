"""完整翻译流程测试 — 4 语言批量翻译。"""
import asyncio
import json
import os
import sys
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "api"))

from domain.translator import translate_display

# 模拟 display JSON（含 Path 3 中文字段）
SAMPLE_DISPLAY = {
    "title": "韩版不锈钢项链女 ins风锁骨链不掉色简约百搭",
    "verdictProduct": "✅ 推荐拿样 — 进价 ¥1.4、3件起批、月销 4.8k+，试错成本极低",
    "verdictFactory": "✅ 工厂可靠 — 6年老店+SGS验厂，合作风险低",
    "supplierName": "义乌市雨灏贸易有限公司",
    "shippingLocation": "浙江省金华市义乌市苏溪镇",
    "factoryFlags": "超级工厂 · 深度验厂",
    "certType": "SGS 实地认证",
    "sellerExplain": "1688 平台认证的生产厂家，具备自主生产能力。",
    "certExplain": "第三方机构实地验厂认证，核实企业生产资质与经营状况。",
    "flagsExplain": "1688 最高规格验厂认证，自有工厂与生产线。",
    "rankExplain": "该商家暂未上榜 1688 品类排名榜单。",
    "salesExplain": "近30天销量4,892件，复购率42%",
    "specs": [
        {"name": "材质", "value": "不锈钢"},
        {"name": "款式", "value": "锁骨链"},
        {"name": "风格", "value": "韩版ins风"},
    ],
    "factory": {
        "factoryFlags": "超级工厂 · 深度验厂",
        "certType": "SGS 实地认证",
        "rankExplain": "该商家暂未上榜 1688 品类排名榜单。",
    },
    # Path 1/2 字段（不应被翻译）
    "trustBar": {"factoryCert": True, "supplyStability": "high"},
    "badges": [
        {"text": "Source Factory", "type": "factory"},
        {"text": "Verified", "type": "cert"},
    ],
    "priceCNY": [{"moq": 3, "price": 1.4, "unit": "件"}],
}


async def main():
    langs = ["en", "vi", "th", "id"]
    for lang in langs:
        print(f"\n{'='*60}")
        print(f"Translating to {lang}...")
        display = json.loads(json.dumps(SAMPLE_DISPLAY))  # deep copy
        result = await translate_display(display, lang)

        translated = result.get("_translatedLang")
        print(f"_translatedLang: {translated}")

        # 显示关键字段翻译结果
        for key in ["title", "verdictProduct", "verdictFactory",
                     "supplierName", "shippingLocation", "factoryFlags",
                     "certType", "sellerExplain", "salesExplain"]:
            old = SAMPLE_DISPLAY.get(key, "")
            new = result.get(key, "")
            if old != new:
                print(f"  [{key}]")
                print(f"    ZH: {old[:80]}")
                print(f"    {lang.upper()}: {str(new)[:80]}")

        if "specs" in result:
            print(f"  [specs]")
            for i, s in enumerate(result["specs"]):
                orig = SAMPLE_DISPLAY["specs"][i]
                if isinstance(s, dict):
                    n = s.get("name", "")
                    v = s.get("value", "")
                    print(f"    [{i}] name: {orig['name']} -> {n}")
                    print(f"    [{i}] value: {orig['value']} -> {v}")


if __name__ == "__main__":
    asyncio.run(main())
