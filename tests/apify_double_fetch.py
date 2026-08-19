"""Apify 双次抓取一致性排查 — 直接调 adapter，不经过后端分析流程。

验证目标：
1. 同一 offer 连续实时抓两次，supplier 信息是否稳定一致（排除「随机错位」）
2. 对比 DB 里落库的 raw_json（id=120），看实时抓取 vs 历史落库是否一致

用法：
  python tests/apify_double_fetch.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API_DIR = Path(__file__).resolve().parent.parent / "src" / "api"
sys.path.insert(0, str(API_DIR))

import aiomysql  # noqa: E402
from config import Config  # noqa: E402
from adapters.apify_adapter import apify_adapter  # noqa: E402

URL = "https://detail.1688.com/offer/991204283590.html"
OFFER_ID = "991204283590"
ANALYSIS_ID = 120  # DB 里刚分析落库的那条

# 要对比的字段路径（"." 表示嵌套）
FIELDS = [
    "title",
    "supplier.companyName",
    "supplier.memberId",
    "supplier.userId",
    "supplier.loginId",
    "supplier.foundedYear",
    "supplier.tpYear",
    "supplier.flags.isFactory",
    "supplier.flags.isYuantouFlagship",
    "winportUrl",
    "shipping.location",
    "price.min",
    "price.max",
    "saledCount",
    "wantBuyCount",
    "stock",
]


def dig(raw: dict, path: str):
    """按 '.' 路径取嵌套字段，不存在返回 None。"""
    cur = raw
    for k in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def extract(raw: dict) -> dict:
    return {p: dig(raw, p) for p in FIELDS}


async def read_db_raw() -> dict:
    conn = await aiomysql.connect(
        host=Config.DB_HOST, port=Config.DB_PORT, user=Config.DB_USER,
        password=Config.DB_PASSWORD, db=Config.DB_NAME, charset="utf8mb4",
        autocommit=True,
    )
    try:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT raw_json FROM analysis WHERE id=%s", (ANALYSIS_ID,))
            row = await cur.fetchone()
            return json.loads(row["raw_json"]) if row and row["raw_json"] else {}
    finally:
        conn.close()


async def main():
    print("=" * 70)
    print(f"offer_id = {OFFER_ID}")
    print("=" * 70)

    # 1. 实时抓取第 1 次
    print("\n[1/3] Apify 实时抓取 #1 ...")
    raw1 = await apify_adapter.fetch_product_by_url(URL)
    print(f"      #1 返回: {'None(空)' if raw1 is None else str(len(raw1)) + ' keys'}")

    await asyncio.sleep(8)

    # 2. 实时抓取第 2 次
    print("\n[2/3] Apify 实时抓取 #2 ...")
    raw2 = await apify_adapter.fetch_product_by_url(URL)
    print(f"      #2 返回: {'None(空)' if raw2 is None else str(len(raw2)) + ' keys'}")

    # 3. 读 DB 落库的 raw_json
    db_raw = await read_db_raw()
    print(f"\n[3/3] DB raw_json (id={ANALYSIS_ID}): {'空' if not db_raw else str(len(db_raw)) + ' keys'}")

    e1 = extract(raw1) if raw1 else None
    e2 = extract(raw2) if raw2 else None
    edb = extract(db_raw) if db_raw else None

    print("\n" + "=" * 70)
    print("字段对比：实时#1 | 实时#2 | DB落库")
    print("=" * 70)
    for p in FIELDS:
        v1 = e1.get(p) if e1 else None
        v2 = e2.get(p) if e2 else None
        vdb = edb.get(p) if edb else None
        mark = "一致" if (v1 == v2 == vdb) else "差异"
        print(f"\n[{mark}] {p}")
        print(f"    #1 = {v1!r}")
        print(f"    #2 = {v2!r}")
        print(f"    DB = {vdb!r}")

    print("\n" + "=" * 70)
    print("结论")
    print("=" * 70)
    if e1 and e2:
        diff12 = [p for p in FIELDS if e1.get(p) != e2.get(p)]
        print(f"实时#1 vs 实时#2 差异字段数: {len(diff12)}")
        if diff12:
            print(f"  差异字段: {diff12}")
        else:
            print("  两次实时抓取完全一致（Apify 抓取稳定）")
    if e1 and edb:
        diff1db = [p for p in FIELDS if e1.get(p) != edb.get(p)]
        print(f"实时#1 vs DB落库 差异字段数: {len(diff1db)}")
        if diff1db:
            print(f"  差异字段: {diff1db}")
        else:
            print("  实时#1 与 DB 落库完全一致（落库过程忠实）")


if __name__ == "__main__":
    asyncio.run(main())
