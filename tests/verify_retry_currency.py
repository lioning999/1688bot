# -*- coding: utf-8 -*-
"""本次改动覆盖测试：prompt 强化 / 判词数字强控(错误清单+带反馈重写) / 货币本地化。

分层（逐层覆盖，跑完出 PASS/FAIL 汇总）：
  L1 单元   — _fmt_money 3语言换算、_build_price/_build_price_tiers 阶梯价、validate_ai_output 错误清单
  L2 集成   — mock Qwen 确定性测流程：首次成功1次调用 / 失败重写成功2次 / 二次失败降级 / 空返回降级 / JSON坏降级
  L3 端到端 — 真 Qwen：3 产品 × 3 语言 = 9 条判词（需 --e2e，调 API）
  L4 静态   — lang JSON 4 语言 currency.symbol 存在性

用法：
  python tests/verify_retry_currency.py        # L1+L2+L4（无需 API key）
  python tests/verify_retry_currency.py --e2e  # 加跑 L3 真 Qwen
"""
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "api"))

import pymysql  # noqa: E402

from config import Config  # noqa: E402
from domain.data.mapper import map_raw  # noqa: E402
from domain.display.ai_verdict import validate_ai_output, _fmt_money  # noqa: E402
from domain.display.builder import build_display, _build_price_tiers  # noqa: E402
from domain.evaluate.evaluator import evaluate_product  # noqa: E402

# 测试产品（覆盖 go/trial/watch 三档 + 阶梯价 + 金额两级）
PRODUCTS = ["991204283590", "1053910572406", "685469710262"]
LANGS = ["en", "vi", "th"]
E2E = "--e2e" in sys.argv

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = ""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'✅' if ok else '❌'} {name} {detail}")


def _load_mapped(offer_id: str):
    conn = pymysql.connect(host=Config.DB_HOST, port=Config.DB_PORT, user=Config.DB_USER,
                           password=Config.DB_PASSWORD, database=Config.DB_NAME, charset="utf8mb4")
    cur = conn.cursor()
    cur.execute("SELECT raw_json FROM analysis WHERE offer_id=%s ORDER BY id DESC LIMIT 1", (offer_id,))
    raw = json.loads(cur.fetchone()[0])
    conn.close()
    return map_raw(raw, f"https://detail.1688.com/offer/{offer_id}.html", offer_id)


def _money(lang: str) -> dict:
    cny = float(Config.CNY_USD_RATE)
    if lang == "en":
        return {"symbol": "$", "per_cny": 1.0 / cny, "decimals": 2}
    if lang == "vi":
        return {"symbol": "₫", "per_cny": float(Config.FX_VND) / cny, "decimals": 0}
    if lang == "th":
        return {"symbol": "฿", "per_cny": float(Config.FX_THB) / cny, "decimals": 0}
    raise ValueError(lang)


# ====================================================================
# L1 单元
# ====================================================================
def l1():
    print("\n[L1 单元] 货币换算 + 校验错误清单")
    m_en, m_vi, m_th = _money("en"), _money("vi"), _money("th")

    # _fmt_money：3 语言 × 关键金额
    cases = [
        ("en 3.5", _fmt_money(3.5, m_en), "$0.49"),
        ("en 45.96", _fmt_money(45.96, m_en), "$6.38"),
        ("vi 3.5", _fmt_money(3.5, m_vi), "₫12,372"),
        ("vi 45.96", _fmt_money(45.96, m_vi), "₫162,456"),
        ("th 3.5", _fmt_money(3.5, m_th), "฿17"),
        ("th 45.96", _fmt_money(45.96, m_th), "฿228"),
        ("none 保持¥", _fmt_money(3.5, None), "¥3.50"),
    ]
    for name, got, want in cases:
        check(f"_fmt_money {name}", got == want, f"got={got} want={want}")

    # _build_price + _build_price_tiers：1053910572406（9-9.5 CNY, 3 tiers）
    mapped = _load_mapped("1053910572406")
    d_en = build_display(mapped, "en", m_en)
    d_th = build_display(mapped, "th", m_th)
    low, high = float(d_en["price"]["low"]), float(d_en["price"]["high"])
    check("主价格 en 换算", abs(low - 1.25) < 1e-6 and abs(high - 1.319444) < 1e-6,
          f"low={low} high={high}")
    low_th, high_th = float(d_th["price"]["low"]), float(d_th["price"]["high"])
    check("主价格 th 换算", abs(low_th - 44.625) < 1e-6 and abs(high_th - 47.104167) < 1e-6,
          f"low={low_th} high={high_th}")

    tiers = d_en["priceTiers"]
    check("阶梯价数量", len(tiers) == 3, f"n={len(tiers)}")
    if tiers:
        t0 = d_en["priceTiers"][0]
        check("阶梯价 首档换算", abs(float(t0["unit_price"]) - 1.319444) < 1e-6,
              f"unit_price={t0.get('unit_price')}")
        t0_th = build_display(mapped, "th", m_th)["priceTiers"][0]
        check("阶梯价 th 换算", abs(float(t0_th["unit_price"]) - 47.104167) < 1e-6,
              f"th unit_price={t0_th.get('unit_price')}")

    # validate_ai_output 错误清单（核心行为回归）
    ai_input = {
        "dimensions": {
            "product": [{"data": "price ฿17/PCS, MOQ 1 PCS, sales 5915 units", "ref": "hot threshold: >1000"}],
            "supplier": [],
        },
        "must_not_say": [], "supplier_must_not_say": ["we guarantee"],
    }
    check("校验 正常→[]", validate_ai_output("price ฿17, sales 5915", [], ai_input, ("product",)) == [])
    e1 = validate_ai_output("price ฿999, sales 5915", [], ai_input, ("product",))
    check("校验 编造数字→清单", len(e1) == 1 and "999" in e1[0], f"errors={e1}")
    e2 = validate_ai_output("we guarantee this, price ฿17", [], ai_input, ("product",))
    check("校验 禁语→清单", any("guarantee" in x for x in e2), f"errors={e2}")
    e3 = validate_ai_output("Worth doing. 价格 ฿17/ชิ้น", [], ai_input, ("product",))
    check("校验 混中文→清单", any("Chinese" in x for x in e3), f"errors={e3}")
    check("校验 纯母语无中文", validate_ai_output("Worth doing. price ฿17", [], ai_input, ("product",)) == [])
    check("校验 summary不查数字", validate_ai_output("random 9999", [], ai_input, ()) == [])


# ====================================================================
# L2 集成（mock Qwen）
# ====================================================================
async def _build_with_fake(fake_chat, offer_id="997997017645", lang="th"):
    from services.ai_verdict_svc import build_with_ai
    mapped = _load_mapped(offer_id)
    money = _money(lang)
    with patch("services.ai_verdict_svc.qwen_adapter.chat", new=fake_chat):
        return await build_with_ai(mapped, lang, money)


def _fake_ai(pv):
    return {"choices": [{"message": {"content": json.dumps({
        "translated_title": "Test product",
        "translated_supplier_name": "Factory X",
        "product_verdict": pv,
        "supplier_verdict": "Supplier is ok.",
        "summary_verdict": "Go. product verified.",
    }, ensure_ascii=False)}}], "usage": {}}


async def l2():
    print("\n[L2 集成] mock Qwen — 重试流程")
    calls = []

    # 2.1 首次成功：只调 1 次
    async def ok_first(messages, timeout):
        calls.append(1)
        return _fake_ai("ราคา ฿17/ชิ้น ยอดขาย 5915 ชิ้น")

    d = await _build_with_fake(ok_first)
    check("成功路径 只调1次", len(calls) == 1, f"calls={len(calls)}")
    check("成功路径 AI判词生效", "฿17" in d["productEval"]["verdict"], d["productEval"]["verdict"][:40])
    calls.clear()

    # 2.2 首次失败→重写→成功：2 次调用，用第二次
    async def fail_then_fix(messages, timeout):
        calls.append(1)
        pv = "ราคา ฿999/ชิ้น" if len(calls) == 1 else "ราคา ฿17/ชิ้น"
        return _fake_ai(pv)

    d = await _build_with_fake(fail_then_fix)
    check("重写路径 调用2次", len(calls) == 2, f"calls={len(calls)}")
    check("重写路径 用第二次", "฿17" in d["productEval"]["verdict"] and "999" not in d["productEval"]["verdict"],
          d["productEval"]["verdict"][:40])
    calls.clear()

    # 2.3 两次都失败 → 降级模板（不再是 AI 文本）
    async def always_bad(messages, timeout):
        calls.append(1)
        return _fake_ai("ราคา ฿999/ชิ้น")

    d = await _build_with_fake(always_bad)
    check("二次失败 调用2次", len(calls) == 2, f"calls={len(calls)}")
    check("二次失败 降级模板", "999" not in d["productEval"]["verdict"], d["productEval"]["verdict"][:40])
    check("二次失败 _aiGenerated仍标记", d.get("_aiGenerated") == "th")
    calls.clear()

    # 2.4 Qwen 返回空 content → 降级
    async def empty_body(messages, timeout):
        return {"choices": [{"message": {"content": ""}}], "usage": {}}

    d = await _build_with_fake(empty_body)
    check("空content 降级", d.get("_aiGenerated") is None, f"aiGenerated={d.get('_aiGenerated')}")
    calls.clear()

    # 2.5 JSON 解析失败 → 降级
    async def bad_json(messages, timeout):
        return {"choices": [{"message": {"content": "not json at all"}}], "usage": {}}

    d = await _build_with_fake(bad_json)
    check("坏JSON 降级", d.get("_aiGenerated") is None, f"aiGenerated={d.get('_aiGenerated')}")


# ====================================================================
# L3 端到端（真 Qwen）
# ====================================================================
def _is_vietnamese(text: str) -> bool:
    return bool(re.search(r"[đơưăôêạảấầẩẫậắằẳẵặ]", text))


def _is_thai(text: str) -> bool:
    return bool(re.search(r"[฀-๿]", text))


def _verify_e2e_product(offer_id: str, lang: str):
    from services.ai_verdict_svc import build_with_ai
    mapped = _load_mapped(offer_id)
    money = _money(lang)
    display = asyncio.run(build_with_ai(mapped, lang, money))
    tag = f"{offer_id[:4]}…/{lang}"

    # 1) AI 生成成功（未降级）
    check(f"[e2e] {tag} AI生成(_aiGenerated)", display.get("_aiGenerated") == lang,
          f"got={display.get('_aiGenerated')}")
    if display.get("_aiGenerated") != lang:
        return

    # 2) 3 判词字段非空 + 重新校验零错误
    ai_input = __import__("domain.display.ai_verdict", fromlist=["pack_ai_input"]).pack_ai_input(
        evaluate_product(mapped), {"signals": {}, "dimensions": []}, {"tier": "wait_data"},
        mapped, lang, money)
    for fld, section in (("productEval", ("product",)), ("supplierEval", ("supplier",)),
                         ("summaryLine", ("product", "supplier"))):
        text = (display.get(fld) or {}).get("verdict", "")
        check(f"[e2e] {tag} {fld} 非空", bool(text and text.strip()), f"text={text[:40]}")
        errs = validate_ai_output(text, [], ai_input, section)
        check(f"[e2e] {tag} {fld} 防编造", errs == [], f"errors={errs}")

    # 3) 主价格换算精确
    pc = mapped.get("priceCNY") or {}
    want_low = round(float(pc.get("low", 0) or 0) * float(money["per_cny"]), 6)
    got_low = float(display["price"]["low"])
    check(f"[e2e] {tag} 主价格换算", abs(got_low - want_low) < 1e-9, f"low={got_low} want={want_low}")

    # 4) 判词货币符号：出现的货币符号必须都是目标符号（判词不提金额也允许，维度数等非金额数字不需符号）
    vtext = (display.get("productEval") or {}).get("verdict", "")
    others = {"en": "₫฿", "vi": "$฿", "th": "$₫"}[lang]
    sym = money["symbol"]
    syms_found = set(re.findall(r"[¥$₫฿]", vtext))
    check(f"[e2e] {tag} 判词货币符号一致", syms_found <= {sym}, f"found={syms_found} vtext={vtext[:50]}")
    check(f"[e2e] {tag} 判词无它币符号", not any(o in vtext for o in others), f"vtext={vtext[:50]}")

    # 5) 母语（vi/th 含母语字符）
    if lang == "vi":
        check(f"[e2e] {tag} 越南语", _is_vietnamese(vtext), f"vtext={vtext[:50]}")
    elif lang == "th":
        check(f"[e2e] {tag} 泰语", _is_thai(vtext), f"vtext={vtext[:50]}")


# ====================================================================
# L4 前端静态
# ====================================================================
def l4():
    print("\n[L4 前端静态] lang JSON currency.symbol")
    base = Path(__file__).resolve().parent.parent / "src" / "chrome-ext" / "lang"
    expect = {"zh": "¥", "en": "$", "vi": "₫", "th": "฿"}
    for lang, sym in expect.items():
        data = json.load(open(base / f"{lang}.json", encoding="utf-8"))
        got = data.get("currency.symbol", "")
        check(f"lang/{lang}.json symbol", got == sym, f"got={got!r} want={sym!r}")


# ====================================================================
def main():
    print("=" * 60)
    print("本次改动覆盖测试 — prompt/数字强控/重试流程/货币")
    print("=" * 60)
    l1()
    asyncio.run(l2())
    l4()
    if E2E:
        if not Config.QWEN_API_KEY:
            print("\n⚠️ QWEN_API_KEY 未配置，跳过 L3")
        else:
            print("\n[L3 端到端] 真 Qwen：3产品 × 3语言（每次 ~5-30s）")
            for offer_id in PRODUCTS:
                for lang in LANGS:
                    t0 = time.time()
                    _verify_e2e_product(offer_id, lang)
                    print(f"    └ 耗时 {time.time()-t0:.1f}s")
    else:
        print("\n（加 --e2e 跑 L3 真 Qwen 端到端）")

    print("\n" + "=" * 60)
    print(f"结果: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        print("失败项:")
        for f in FAIL:
            print("  ❌", f)
    print("=" * 60)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
