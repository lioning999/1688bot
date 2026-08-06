"""抓取 1688 商品 → 跑完整管线 → 输出 display JSON → 可前端直接查看。

用法：
  cd src/api
  python -X utf8 ../../tests/fetch_and_render.py

输出：
  tests/data/{offer_id}_raw.json     — Apify 原始数据
  tests/data/{offer_id}_mapped.json  — mapper 中间产物
  src/web/samples/{offer_id}/data.json      — 前端样本数据
  src/web/samples/{offer_id}/display_zh.json — display JSON（中文）
"""
import asyncio
import json
import os
import sys
from pathlib import Path

# 确保 src/api 在 path 中
API_DIR = Path(__file__).resolve().parent.parent / "src" / "api"
sys.path.insert(0, str(API_DIR))

from domain.product_mapper import map_raw
from domain.display_builder import build_display
from domain.evaluator import evaluate_product, evaluate_supplier, evaluate_summary

URL = "https://detail.1688.com/offer/894464302316.html"
OFFER_ID = "894464302316"


def safe_json(obj, max_depth=3, cur_depth=0):
    """递归转 JSON-safe 对象，截断深层嵌套。"""
    if cur_depth > max_depth:
        return str(obj)[:200]
    if isinstance(obj, dict):
        return {str(k): safe_json(v, max_depth, cur_depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [safe_json(item, max_depth, cur_depth + 1) for item in obj]
    if isinstance(obj, (int, float, bool)) or obj is None:
        return obj
    return str(obj)[:500]


async def main():
    # 目录
    data_dir = Path(__file__).resolve().parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    samples_dir = Path(__file__).resolve().parent.parent / "src" / "web" / "samples" / OFFER_ID
    samples_dir.mkdir(parents=True, exist_ok=True)

    # ===================================================================
    # 1. Apify 抓取
    # ===================================================================
    print(f"[1/5] Apify 抓取 {URL}...")
    from adapters.apify_adapter import apify_adapter

    raw = await apify_adapter.fetch_product_by_url(URL)
    if raw is None:
        print("❌ Apify 返回空（可能已下架或配额耗尽）")
        return

    raw_path = data_dir / f"{OFFER_ID}_raw.json"
    raw_path.write_text(json.dumps(safe_json(raw), ensure_ascii=False, indent=2), encoding="utf-8")
    key_count = len(raw)
    print(f"   ✅ 原始数据 {key_count} keys → {raw_path}")

    # ===================================================================
    # 2. Mapper
    # ===================================================================
    print(f"[2/5] 映射标准化字段...")
    mapped = map_raw(raw, URL, OFFER_ID)

    mapped_path = data_dir / f"{OFFER_ID}_mapped.json"
    mapped_path.write_text(json.dumps(safe_json(mapped), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   ✅ mapped {len(mapped)} keys → {mapped_path}")

    # ===================================================================
    # 3. Evaluator（新引擎）
    # ===================================================================
    print(f"[3/5] 新引擎评估...")
    pe = evaluate_product(mapped)
    se = evaluate_supplier(mapped)
    sm = evaluate_summary(pe, se)

    print(f"   产品: tier={pe['tier']} grade={pe['grade']} score={pe['score']}/{pe['max_score']}")
    print(f"   供应商: tier={se['tier']} grade={se['grade']} score={se['score']}/{se['max_score']}")
    print(f"   综合: tier={sm['tier']}")
    print(f"   产品判词: {json.dumps(pe['verdict'], ensure_ascii=False)[:120]}")
    print(f"   供应商判词: {json.dumps(se['verdict'], ensure_ascii=False)[:120]}")
    print(f"   综合 headline: {json.dumps(sm['headline'], ensure_ascii=False)}")

    # ===================================================================
    # 4. Display 构建
    # ===================================================================
    print(f"[4/5] 构建 display JSON（中文）...")
    display = build_display(mapped, lang="zh")

    display_path = samples_dir / "display_zh.json"
    display_path.write_text(json.dumps(display, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   ✅ display_zh.json {display_path.stat().st_size} bytes → {display_path}")

    # ===================================================================
    # 5. 保存原始数据副本到 samples/
    # ===================================================================
    print(f"[5/5] 复制数据到 samples...")
    data_path = samples_dir / "data.json"
    data_path.write_text(json.dumps(safe_json(raw), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   ✅ data.json → {data_path}")

    print()
    print("=" * 60)
    print("✅ 全部完成！浏览器打开：")
    print(f"   http://localhost:8008/inspect.html?sample={OFFER_ID}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
