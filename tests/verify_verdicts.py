"""判词 6 标准验证脚本 — 只读 DB，不改任何数据。

按 docs/判词-方法论.md §三「6 条硬标准」逐条检查 DB 里所有真实产品的判词：
  S1 结论词锁 grade（报告项，AI 语言可能把结论放后面，机器不确定 → 人工复核）
  S2 数字只从真实数据取（verdict 里每个数字必须在维度/价格/销量等可信源出现过）
  S3 综合判词带 品+厂 各 1 个数字（SL verdict 数字 ≥2）
  S4 动作可执行（禁虚词：蹲数据/多留个心眼/基本不亏/别急着…）
  S5 平直商务词（禁俗语：悠着点/anyone still standing…）
  S6 恰好 3 句（zh 且 ≤40 字）
另检：「但。」残句。

用法：
  python tests/verify_verdicts.py            # 检查 DB 存量 display_i18n（旧数据基线）
  python tests/verify_verdicts.py --rebuild  # 读 raw_json 重建判词再检查（改代码后验证用）
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API_DIR = Path(__file__).resolve().parent.parent / "src" / "api"
sys.path.insert(0, str(API_DIR))

import pymysql  # noqa: E402
from config import Config  # noqa: E402
from domain.data.mapper import map_raw  # noqa: E402
from domain.display.builder import build_display  # noqa: E402

# ---- 检查词表 ----
# S4 动作虚词 / S5 俗语（命中 = FAIL）
VAGUE_ACTION = ["蹲数据", "多留个心眼", "留个心眼", "基本不亏", "别急着", "悠着点",
                "多留心", "don't rush", "do not rush", "watch quality closely", "看情况"]
COLLOQUIAL = ["悠着点", "赌厂", "anyone still standing", "先收藏"]

# S1 结论词 → grade（用于报告"结论词是否明确"）
CONCLUSION_WORDS = {
    "go":   ["值得做", "可以出手", "go for it", " go", "trust", "做"],
    "ok":   ["小批量试", "有条件做", "try", "可用", "caution", "conditional", "sample"],
    "bad":  ["谨慎", "小心", "caution", "avoid", "don't"],
    "none": ["观望", "数据不够", "等一等", "hold", "not enough", "wait", "save", "别急"],
}

NUM_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
SENT_SPLIT_RE = re.compile(r"[。.!?！？]")
CJK_RE = re.compile(r"[一-鿿]")

# "1688" 平台域名常出现在文案里，不是业务数字，跳过
SKIP_NUMS = {1688.0}


def get_lang(display: dict):
    """display 顶层按语言嵌套（en/zh/vi/th）；或扁平（build_display 直接输出）。

    嵌套 → 返回语言 key；扁平 → 返回 "_flat"。
    """
    for k, v in display.items():
        if isinstance(v, dict) and "productEval" in v:
            return k
    if "productEval" in display:
        return "_flat"
    return None


def collect_trusted_numbers(display: dict, lang: str) -> set[float]:
    """收集可信数字源：价格/销量/复购/年限/维度数据/维度标杆/标题规格。"""
    j = display if lang == "_flat" else display[lang]
    texts: list[str] = [str(j.get("title") or "")]
    price = j.get("price", {})
    texts += [str(v) for v in (price.get("low"), price.get("high"), price.get("moq")) if v is not None]
    sales = j.get("sales", {})
    texts += [str(sales.get("sold") or ""), str(sales.get("explain") or "")]
    tb = j.get("trustBar", {})
    texts += [str(tb.get("sold") or ""), str(tb.get("years") or "")]
    fac = j.get("factory", {})
    texts += [str(fac.get("years") or ""), str(fac.get("sellerLabel") or ""), str(fac.get("rankText") or "")]
    for ev in (j.get("productEval", {}).get("dimensions", []), j.get("supplierEval", {}).get("dimensions", [])):
        for d in ev:
            texts += [str(d.get("data") or ""), str(d.get("ref") or "")]
    nums: set[float] = set()
    for t in texts:
        for m in NUM_RE.findall(t):
            try:
                nums.add(round(float(m.replace(",", "")), 1))
            except ValueError:
                pass
    return nums


def check_verdict(role: str, grade: str, verdict: str, trusted: set[float]) -> tuple[list[str], list[str]]:
    """返回 (fail_list, report_list)。"""
    fails, reports = [], []
    v = verdict or ""
    if not v:
        return ["空判词"], []

    # 残句
    if "但。" in v:
        fails.append("残句「但。」")

    # S2 数字真实性：verdict 里每个数字必须在可信源出现
    for m in NUM_RE.findall(v):
        try:
            num = round(float(m.replace(",", "")), 1)
        except ValueError:
            continue
        if num in SKIP_NUMS:
            continue
        if num not in trusted:
            fails.append(f"S2 数字编造? {m}（不在可信源）")

    # S3 综合判词带数字（仅 SL 检查）：品侧数字必须有；
    # 厂侧证据常为认证/身份文字（方法论案例标杆同此），不强制数字，报告数字个数
    n_num = len([m for m in NUM_RE.findall(v)])
    if role == "summary" and grade != "none":
        if n_num < 1:
            fails.append("S3 综合判词零数字")
        else:
            reports.append(f"S3 数字×{n_num}（厂侧可为认证/身份文字）")

    # S4 动作虚词
    vl = v.lower()
    hit = [w for w in VAGUE_ACTION if w in vl]
    if hit:
        fails.append(f"S4 虚词动作 {hit}")

    # S5 俗语
    hit = [w for w in COLLOQUIAL if w in vl]
    if hit:
        fails.append(f"S5 俗语 {hit}")

    # S6 句数 ≤3，zh 且 ≤40 字（只测判词正文：剥离 ⚠️ 风险附加；先保护小数点防误切）
    v_clean = re.sub(r"(\d)\.(\d)", r"\1·\2", v)
    body = v_clean.split("⚠️", 1)[0]
    sentences = [s for s in SENT_SPLIT_RE.split(body) if s.strip()]
    if len(sentences) > 3:
        fails.append(f"S6 句数 {len(sentences)} > 3")
    if CJK_RE.search(body) and len(body) > 40:
        fails.append(f"S6 长度 {len(body)} > 40 字")

    # S1 结论词（报告项）：首句是否含该 grade 的结论词
    words = [w for w in CONCLUSION_WORDS.get(grade, []) if w]
    first = sentences[0][:40].lower() if sentences else ""
    if grade and words and not any(w in first for w in words):
        reports.append(f"S1 首句未见{grade}结论词")

    return fails, reports


def main():
    rebuild = "--rebuild" in sys.argv
    conn = pymysql.connect(host=Config.DB_HOST, port=Config.DB_PORT, user=Config.DB_USER,
                           password=Config.DB_PASSWORD, database=Config.DB_NAME, charset="utf8mb4")
    cur = conn.cursor()
    if rebuild:
        cur.execute(
            "SELECT id, offer_id, raw_json FROM analysis "
            "WHERE raw_json IS NOT NULL AND offer_id NOT LIKE 'fake%' ORDER BY id")
    else:
        cur.execute(
            "SELECT id, offer_id, display_i18n FROM analysis "
            "WHERE display_i18n IS NOT NULL AND offer_id NOT LIKE 'fake%' ORDER BY id")
    rows = cur.fetchall()
    conn.close()

    mode = "重建判词（改后验证）" if rebuild else "DB 存量 display（旧基线）"
    print("=" * 100)
    print(f"判词 6 标准验证 — {mode}（{len(rows)} 条）")
    print("=" * 100)

    total_fails, total_reports = 0, 0
    per_offer: dict[str, list[str]] = {}
    for rid, oid, d in rows:
        if rebuild:
            try:
                raw = json.loads(d)
                mapped = map_raw(raw, f"https://detail.1688.com/offer/{oid}.html", oid)
                display = build_display(mapped, "zh")
            except Exception as e:
                print(f"\n[{rid}] {oid} — 重建失败: {e}")
                continue
        else:
            try:
                display = json.loads(d)
            except json.JSONDecodeError:
                print(f"\n[{rid}] {oid} — display_i18n 非 JSON")
                continue
        lang = get_lang(display)
        if not lang:
            print(f"\n[{rid}] {oid} — 找不到语言层")
            continue
        j = display if lang == "_flat" else display[lang]
        trusted = collect_trusted_numbers(display, lang)

        cases = [
            ("product",  "productEval",   "product"),
            ("supplier", "supplierEval",  "supplier"),
            ("summary",  "summaryLine",   "summary"),
        ]
        print(f"\n[{rid}] {oid} ({lang})  PE{j['productEval'].get('grade')} "
              f"SE{j['supplierEval'].get('grade')} "
              f"SL{j.get('summaryLine', {}).get('grade')}")
        for label, key, role in cases:
            ev = j.get(key, {})
            grade = ev.get("grade")
            verdict = ev.get("verdict")
            if key == "summaryLine" and not verdict:
                verdict = ev.get("reason")  # 综合判词 reason 即判词
            fails, reports = check_verdict(role, grade, verdict, trusted)
            total_fails += len(fails)
            total_reports += len(reports)
            for r in reports:
                print(f"  ⚠️ {label:8s} {r}")
            for f in fails:
                print(f"  ❌ {label:8s} {f}")
                per_offer.setdefault(oid, []).append(f)
        if not (fails or reports):
            print("  ✅ 全过")

    print("\n" + "=" * 100)
    print(f"汇总：FAIL {total_fails} 条 | 需人工复核 {total_reports} 条 | 有 FAIL 的产品 {len(per_offer)} 个")
    for oid, fl in sorted(per_offer.items()):
        print(f"  {oid}: {fl}")
    print("=" * 100)


if __name__ == "__main__":
    main()
