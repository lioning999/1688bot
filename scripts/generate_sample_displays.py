"""从 data.json + display_builder 生成 3 个案例的 15 个 display_{lang}.json。

使用方式：
  cd d:\AI-Code\gaoqian
  python scripts/generate_sample_displays.py

策略（两层合并）：
  📖 GL 层 → display_builder.build_display() 生成（trustBar/badges/verdicts/factory explainers）
  🤖 Qwen 层 → 现有 {lang}.json 中的翻译字段覆盖（title/specs/skus/name/sh location）

输出形状和 /api/report 返回的 result.display 一致，前端 renderV2 直接可用。
"""
import json
import sys
from pathlib import Path
from typing import Any

# 确保 src/api 在 sys.path 中
API_DIR = Path(__file__).resolve().parent.parent / "src" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from domain.verdict_engine import judge_all, _fmt_k       # noqa: E402
from domain.display_builder import (                        # noqa: E402
    build_display, _s, _STAR_SYMBOLS,
)

SAMPLES = ["muhezi", "taiyangjing", "iphonecase"]
LANGS = ["zh", "en", "vi", "th", "id"]
SAMPLES_DIR = Path(__file__).resolve().parent.parent / "src" / "web" / "samples"

# ---- 加载 zh glossary（用于 zh display 构建） ----
_ZH_PATH = Path(__file__).resolve().parent.parent / "src" / "web" / "lang" / "glossary" / "zh.json"
with open(_ZH_PATH, "r", encoding="utf-8") as _f:
    _ZH_GL: dict[str, str] = json.load(_f)


def _zh_gl(key: str, default: str = "") -> str:
    if key in _ZH_GL:
        return _ZH_GL[key]
    return default or key


def _build_zh_display(data: dict[str, Any]) -> dict[str, Any]:
    """构建 zh display JSON：data.json 中文字段 + zh glossary 查表。"""
    cny: dict = data.get("priceCNY") or {}
    dt = _s(data.get("dataTier"))
    tier_label = _s(data.get("sellerTierLabel"))
    sold_n = _fmt_k(data.get("sold")) if data.get("sold") else ""

    # trustBar
    reason_map = {"sufficient": "tier_sufficient_2y", "partial": "tier_factory_1y", "limited": "tier_insufficient"}
    trust_bar = {
        "label": _zh_gl(tier_label, tier_label),
        "sold": _zh_gl("trust_sold_fmt").replace("{n}", sold_n) if sold_n else "",
        "years": _zh_gl("trust_years_fmt").replace("{n}", str(data.get("shop_years") or "")) if data.get("shop_years") else "",
        "stars": _STAR_SYMBOLS.get(dt, ""),
        "tier": _zh_gl(f"star_{dt}_label", ""),
        "tierReason": _zh_gl(reason_map.get(dt, ""), data.get("dataTierReason", "")),
    }

    # badges — 和 display_builder._build_badges 行为一致：3 类
    badges: list[dict[str, str]] = []
    # ① 7 天退货
    if data.get("return7day") == "OK":
        t_7d = _zh_gl("7天无理由退货", "7-Day Returns")
        badges.append({"text": t_7d, "html": f'<span class="badge-sm green">{t_7d}</span>'})
    # ② 回头率
    rp = data.get("repurchase")
    if rp:
        rp_text = _zh_gl("badge_repurchase_fmt").replace("{n}", str(rp))
        badges.append({"text": rp_text, "html": f'<span class="badge-sm gold">{rp_text}</span>'})
    # ③ 支持混批
    badge_labels = data.get("badgeLabels") or []
    if any(b.get("label") == "支持混批" for b in badge_labels):
        mixed_text = _zh_gl("支持混批", "Mixed Batch OK")
        badges.append({"text": mixed_text, "html": f'<span class="badge-sm green">{mixed_text}</span>'})

    # factory explainers
    f_flags = _s(data.get("factoryFlags"))
    cert_type = _s(data.get("certType"))
    rank_text = _s(data.get("rankText"))
    emoji = _zh_gl("emoji_factory", "🏭 ")
    emoji_r = _zh_gl("emoji_rank", "🏆 ")

    if tier_label == "源头工厂":
        seller_exp = _zh_gl("explain_seller_factory")
    elif tier_label == "贸易商":
        seller_exp = _zh_gl("explain_seller_trader")
    else:
        seller_exp = ""

    if "非生产厂家" in f_flags:
        flags_exp = _zh_gl("explain_flags_trader")
    elif "超级工厂" in f_flags:
        flags_exp = _zh_gl("explain_flags_super")
    elif "源头旗舰" in f_flags:
        flags_exp = _zh_gl("explain_flags_flagship")
    elif "实力工厂" in f_flags:
        flags_exp = _zh_gl("explain_flags_shili")
    elif f_flags and f_flags != "非生产厂家":
        flags_exp = _zh_gl("explain_flags_self_claimed")
    else:
        flags_exp = ""

    cert_exp = _zh_gl("explain_cert_has") if cert_type else _zh_gl("explain_cert_none")
    rank_exp = _zh_gl("explain_rank_none") if not rank_text else ""

    # industryCluster
    loc = _s(data.get("shippingLocation"))
    city_map = {
        "金华": "industry_yiwu", "义乌": "industry_yiwu", "广州": "industry_guangzhou",
        "深圳": "industry_shenzhen", "晋江": "industry_jinjiang", "南通": "industry_nantong",
        "泉州": "industry_quanzhou", "东莞": "industry_dongguan", "佛山": "industry_foshan",
        "杭州": "industry_hangzhou", "温州": "industry_wenzhou", "宁波": "industry_ningbo",
        "绍兴": "industry_shaoxing", "澄海": "industry_chenghai", "永康": "industry_yongkang",
        "诸暨": "industry_zhuji", "潮州": "industry_chaozhou",
        "台州": "industry_taizhou", "汕头": "industry_shantou",
    }
    ikey = ""
    for city, key in city_map.items():
        if city in loc:
            ikey = key
            break
    idesc = _zh_gl(ikey) if ikey else ""
    ifmt = _zh_gl("explain_industry_fmt", "{industry}")
    industry_explain = ifmt.format(industry=idesc) if idesc else ""

    factory = {
        "sellerLabel": f"{emoji}{_zh_gl(tier_label, tier_label)}" if tier_label else "",
        "sellerExplain": seller_exp,
        "companyNameExplain": _zh_gl("explain_company_name"),
        "certType": cert_type,
        "certExplain": cert_exp,
        "certReportUrl": _s(data.get("certReportUrl")),
        "shopUrl": _s(data.get("shopUrl")),
        "factoryFlags": f_flags,
        "flagsExplain": flags_exp,
        "rankText": f"{emoji_r}{rank_text}" if rank_text else "",
        "rankExplain": rank_exp,
        "supplierName": _s(data.get("supplierName")),
        "companyName": _s(data.get("companyName")),
        "shippingLocation": loc,
        "industryCluster": industry_explain,
    }

    # sales
    sales = {
        "sold": _zh_gl("sales_sold_fmt").replace("{n}", _fmt_k(data.get("sold")) if data.get("sold") else ""),
        "explain": _zh_gl("explain_sales_high"),
    }

    return {
        "title": _s(data.get("title")),
        "titleOrig": _s(data.get("title")),
        "images": data.get("images") or [],
        "videoUrl": _s(data.get("videoUrl")),
        "itemUrl": _s(data.get("itemUrl")),
        "offerId": _s(data.get("offerId")),
        "price": {
            "low": cny.get("low", 0) if isinstance(cny, dict) else 0,
            "high": cny.get("high", 0) if isinstance(cny, dict) else 0,
            "moq": data.get("moq"),
            "unit": _zh_gl(f"unit_{_s(data.get('unit'))}", _s(data.get("unit"))),
        },
        "trustBar": trust_bar,
        "badges": badges,
        "specs": data.get("specs") or [],
        "sales": sales,
        "skus": data.get("skus") or [],
        "verdictProduct": _fmt_zh_verdict(data.get("verdict_product", {})),
        "verdictFactory": _fmt_zh_verdict(data.get("verdict_factory", {})),
        "verdictSample": _fmt_zh_verdict(data.get("verdict_sample", {})),
        "factory": factory,
    }


def _fmt_zh_verdict(v: Any) -> str:
    if not v:
        return ""
    if isinstance(v, str):
        return v
    if not isinstance(v, dict):
        return ""
    key = str(v.get("key", ""))
    if not key:
        return ""
    template = _zh_gl(key)
    if not template:
        return ""
    params: dict = v.get("params", {}) or {}
    try:
        return template.format(**params)
    except (KeyError, ValueError):
        return template


def _merge_translated(display: dict, translated: dict) -> dict:
    """把 {lang}.json 中的 🤖 Qwen 翻译字段 覆盖到 display JSON 上。"""
    if not translated:
        return display
    # title / specs / skus — Qwen 翻译
    for key in ("title", "titleOrig"):
        if translated.get(key):
            display[key] = translated[key]
    if translated.get("specs"):
        display["specs"] = translated["specs"]
    if translated.get("skus"):
        display["skus"] = translated["skus"]
    # factory 中的 🤖 Qwen 翻译字段
    tf = translated.get("factory") or {}
    df = display.get("factory") or {}
    for key in ("supplierName", "shippingLocation", "factoryFlags", "rankText"):
        if tf.get(key):
            df[key] = tf[key]
    # 注：sellerLabel/verdicts 在 build_display 中已通过 📖 GL 正确生成，不覆盖
    display["factory"] = df
    return display


def generate() -> None:
    for sample in SAMPLES:
        sample_dir = SAMPLES_DIR / sample
        data_path = sample_dir / "data.json"
        if not data_path.exists():
            print(f"[SKIP] {data_path} 不存在")
            continue

        with open(data_path, "r", encoding="utf-8") as f:
            data: dict = json.load(f)

        # 用 verdict engine 重算判词（{key, params}，确保多语言正确）
        verdicts = judge_all(data)
        data["verdict_product"] = verdicts["product"]
        data["verdict_factory"] = verdicts["factory"]
        data["verdict_sample"] = verdicts["sample"]

        for lang in LANGS:
            if lang == "zh":
                display = _build_zh_display(data)
            else:
                display = build_display(data, lang)
                # 加载 {lang}.json 中的 🤖 Qwen 翻译字段覆盖
                translated_path = sample_dir / f"{lang}.json"
                translated: dict = {}
                if translated_path.exists():
                    with open(translated_path, "r", encoding="utf-8") as f:
                        translated = json.load(f)
                display = _merge_translated(display, translated)

            out_path = sample_dir / f"display_{lang}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(display, f, ensure_ascii=False, indent=2)
            print(f"[OK] {out_path.relative_to(SAMPLES_DIR)}")

    print("\nDone — 15 display JSONs generated.")


if __name__ == "__main__":
    generate()
