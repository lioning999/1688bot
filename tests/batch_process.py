"""批量处理 3 个 1688 商品：已有 JSON + 2 个 URL → display JSON → samples。
用法：cd src/api && python -X utf8 ../../tests/batch_process.py
"""
import asyncio, json, sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent / "src" / "api"
sys.path.insert(0, str(API_DIR))

from domain.product_mapper import map_raw
from domain.display_builder import build_display
from domain.evaluator import evaluate_product, evaluate_supplier, evaluate_summary

SAMPLES = Path(__file__).resolve().parent.parent / "src" / "web" / "samples"

ITEMS = [
    {
        "name": "太阳镜",
        "type": "file",
        "path": str(Path(__file__).resolve().parent / "apify_raw_response_723736665098.json"),
        "offer_id": "723736665098",
        "url": "https://detail.1688.com/offer/723736665098.html",
    },
    {
        "name": "商品2",
        "type": "url",
        "url": "https://detail.1688.com/offer/1072003774933.html",
        "offer_id": "1072003774933",
    },
    {
        "name": "商品3",
        "type": "url",
        "url": "https://detail.1688.com/offer/1062465593257.html",
        "offer_id": "1062465593257",
    },
]


async def process_one(item):
    offer_id = item["offer_id"]
    raw_url = item.get("url", f"https://detail.1688.com/offer/{offer_id}.html")

    print(f"\n{'='*60}")
    print(f"  {item['name']} — offer/{offer_id}")
    print(f"{'='*60}")

    # 1. 获取原始数据
    if item["type"] == "file":
        raw = json.loads(Path(item["path"]).read_text(encoding="utf-8"))
        print(f"  [1/4] 读取已有文件: {len(raw)} keys")
    else:
        from adapters.apify_adapter import apify_adapter
        print(f"  [1/4] Apify 抓取...")
        raw = await apify_adapter.fetch_product_by_url(raw_url)
        if raw is None:
            print(f"  ❌ Apify 返回空")
            return None
        print(f"  ✅ {len(raw)} keys")

    # 保存原始数据
    data_dir = Path(__file__).resolve().parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / f"{offer_id}_raw.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # 2. Mapper
    print(f"  [2/4] 映射...")
    mapped = map_raw(raw, raw_url, offer_id)
    (data_dir / f"{offer_id}_mapped.json").write_text(
        json.dumps(mapped, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # 3. 评估
    print(f"  [3/4] 评估...")
    pe = evaluate_product(mapped)
    se = evaluate_supplier(mapped)
    sm = evaluate_summary(pe, se)

    print(f"  产品: tier={pe['tier']:25s} grade={pe['grade']:5s} score={pe['score']}/{pe['max_score']}")
    print(f"  供应商: tier={se['tier']:25s} grade={se['grade']:5s} score={se['score']}/{se['max_score']}")
    print(f"  综合: tier={sm['tier']:30s} → {sm.get('headline',{}).get('key','?')}")

    # 4. Display
    print(f"  [4/4] 构建 display...")
    display = build_display(mapped, lang="zh")

    sample_dir = SAMPLES / offer_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    (sample_dir / "display_zh.json").write_text(
        json.dumps(display, ensure_ascii=False, indent=2), encoding="utf-8")
    (sample_dir / "data.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(f"  ✅ display_zh.json → {sample_dir}")
    return {"offer_id": offer_id, "pe": pe, "se": se, "sm": sm}


async def main():
    results = []
    for item in ITEMS:
        result = await process_one(item)
        results.append(result)

    # 汇总
    print(f"\n{'='*60}")
    print(f"  汇总比较")
    print(f"{'='*60}\n")
    print(f"{'商品':12s} | {'产品 Tier':25s} | {'供应商 Tier':25s} | {'综合 Tier':30s} | 分")
    print("-" * 115)
    all_items = [
        ("连衣裙", "watch_medium12", "caution_weak2", "wait_data", "9/18 + 4/9"),
        ("转转马", "go_hot_wanted", "caution_weak2", "conditional_supplier_weak", "12/18 + 4/9"),
    ]
    for r in results:
        if r:
            pe, se, sm = r["pe"], r["se"], r["sm"]
            all_items.append((
                ITEMS[[i for i, x in enumerate(ITEMS) if x["offer_id"] == r["offer_id"]][0]]["name"],
                pe["tier"], se["tier"], sm["tier"],
                f"{pe['score']}/{pe['max_score']} + {se['score']}/{se['max_score']}"
            ))

    for name, pt, st, mt, sc in all_items:
        print(f"{name:12s} | {pt:25s} | {st:25s} | {mt:30s} | {sc}")

    print(f"\n✅ 全部样本就绪。浏览器打开：")
    for r in results:
        if r:
            print(f"   http://localhost:8008/inspect.html?sample={r['offer_id']}")


if __name__ == "__main__":
    asyncio.run(main())
