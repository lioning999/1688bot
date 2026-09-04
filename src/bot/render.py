"""Display JSON → Telegram 俄语报告（HTML parse_mode）。纯函数，可单测。

报告 = 3 条消息（2026-09-01 拍板）：
  render_card(display)     → 第 1 条 caption：产品图 + 核心结论（标题/价格/MOQ/销量/Summary）
  render_product(display)  → 第 2 条正文：产品验证（4 维 + 🏆 排名/📦 库存）
  render_supplier(display) → 第 3 条正文：供应商验证（5 维 + 公司/产业带）

内容/布局对齐插件 sidepanel.js 显示结构；价格俄式（₽ 在后、空格千分位、逗号小数）。
上游文案全部 html.escape，防 Telegram 解析报错（防坑 #1）。
"""

import html as _html
from typing import Any

from i18n import t


def _s(v: Any) -> str:
    return str(v) if v is not None else ""


def esc(v: Any) -> str:
    return _html.escape(_s(v), quote=True)


def _rub(v: Any) -> str:
    """俄式数字：千分位空格（俄语逗号是小数位）、有小数才逗号、无小数不留尾零。"""
    try:
        f = float(v)
    except (ValueError, TypeError):
        return _s(v)
    if f == int(f):
        return f"{int(f):,}".replace(",", " ")
    s = f"{f:,.2f}".rstrip("0").rstrip(".")
    return s.replace(",", " ").replace(".", ",")


def _grade_emoji(grade: str) -> str:
    """summaryLine.grade → 结论 emoji（对齐插件 grade 色块语义）。"""
    return {"go": "🟢", "ok": "🟡", "bad": "🔴", "none": "⚪"}.get(grade or "", "⚪")


def _price_line(price: dict[str, Any]) -> str:
    """💰 157–801 ₽ · MOQ 500 шт.（俄式：₽ 在后带空格）"""
    parts: list[str] = []
    lo, hi = price.get("low"), price.get("high")
    if lo is not None or hi is not None:
        num = f"{_rub(lo)}–{_rub(hi)}" if (lo is not None and hi is not None and hi != lo) else _rub(lo if lo is not None else hi)
        parts.append(f"💰 {num} ₽")
    if price.get("moq") is not None:
        unit = f" {esc(price['unit'])}" if price.get("unit") else ""
        parts.append(f"MOQ {esc(price['moq'])}{unit}")
    return " · ".join(parts)


def _dim_block(dim: dict[str, Any]) -> str:
    """维度两行式：`mark icon 名称:` 换行 `　　数据 (ref)`。全角空格缩进，HTML 不合并。"""
    name = _s(dim.get("name"))
    data = _s(dim.get("data"))
    if not name and not data:
        return ""
    # 维度标记（对齐插件 _renderDimRows）：na/0 → —，score≥2 → ✔，score==1 → ✘
    score = dim.get("score")
    if dim.get("na") or score == 0:
        mark = "—"
    elif isinstance(score, (int, float)) and score >= 2:
        mark = "✔"
    else:
        mark = "✘"
    icon = _s(dim.get("icon"))
    label = f"{mark} {icon} <b>{esc(name)}</b>:" if icon else f"{mark} <b>{esc(name)}</b>:"
    body = esc(data)
    ref = _s(dim.get("ref"))
    if body:
        label += "\n　　" + body  # 数据行：全角空格 ×2 缩进（HTML 只合并 ASCII 空白）
    if ref:
        label += "\n　　(" + esc(ref) + ")"  # 标准独立一行，与数据同缩进
    return label


def _is_bad(dim: dict[str, Any]) -> bool:
    """致命维度（✘）判定：score==1 才算风险；na/0 和达标(≥2)算正常项。"""
    score = dim.get("score")
    if dim.get("na") or score == 0:
        return False
    if isinstance(score, (int, float)) and score >= 2:
        return False
    return True


def render_card(display: dict[str, Any]) -> str:
    """第 1 条 caption：标题 + 价格/MOQ/销量 + Summary 结论。缺字段自适应跳过。"""
    d = display or {}
    lines: list[str] = []

    title = esc(_s(d.get("title")))[:120]
    if title:
        lines.append(f"<b>{title}</b>")

    price: dict[str, Any] = d.get("price") or {}
    pl = _price_line(price)
    if pl:
        lines.append(pl)

    meta: list[str] = []
    sales: dict[str, Any] = d.get("sales") or {}
    if sales.get("sold"):
        meta.append(f"🔥 {esc(sales['sold'])}")
    if meta:
        lines.append(" · ".join(meta))

    # Summary 结论（前置，进第 1 条）
    sl: dict[str, Any] = d.get("summaryLine") or {}
    if sl.get("headline") or sl.get("reason"):
        lines.append("")
        lines.append(t("report.summary"))
        if sl.get("headline"):
            emoji = _grade_emoji(_s(sl.get("grade")))
            headline = esc(sl["headline"])
            if emoji and not headline.startswith(emoji):  # Qwen headline 自带 emoji 时不重复加
                headline = f"{emoji} {headline}"
            lines.append(f"<b>{headline}</b>")
        if sl.get("reason"):
            lines.append(esc(sl["reason"]))

    return "\n".join(lines)


def render_product(display: dict[str, Any]) -> str:
    """第 2 条正文：产品验证（🏆 类目排名 + ✔ 信任项在前、✘ 风险集中尾部）。"""
    d = display or {}
    pe: dict[str, Any] = d.get("productEval") or {}
    if not pe:
        return ""
    lines: list[str] = []
    score = f" {esc(t('report.scoreFmt', score=pe.get('score', 0), max=pe.get('max_score', 0)))}"
    lines.append(f"<b>{t('report.productEval')}{score}</b>")
    # 🏆 类目排名（rankText 已带 🏆 前缀，AI 翻译；缺失则跳过）
    factory: dict[str, Any] = d.get("factory") or {}
    fac_rank = _s(factory.get("rankText"))
    if fac_rank:
        lines.append(esc(fac_rank))
    dims_in: list[Any] = pe.get("dimensions") or []
    dims: list[dict[str, Any]] = [x for x in dims_in if _dim_block(x)]
    good = [x for x in dims if not _is_bad(x)]
    bad = [x for x in dims if _is_bad(x)]
    for dim in good:
        lines.append(_dim_block(dim))
    if bad:
        lines.append(f"<b>{t('report.risk')}</b>")
        for dim in bad:
            lines.append(_dim_block(dim))
    if pe.get("stockLevel") and pe["stockLevel"].get("text"):
        lines.append(f"📦 {esc(pe['stockLevel']['text'])}")
    return "\n".join(lines)


def render_supplier(display: dict[str, Any]) -> str:
    """第 3 条正文：供应商验证（✔/— 前、✘ 后，含公司/产业带）。"""
    d = display or {}
    se: dict[str, Any] = d.get("supplierEval") or {}
    if not se:
        return ""
    lines: list[str] = []
    score = f" {esc(t('report.scoreFmt', score=se.get('score', 0), max=se.get('max_score', 0)))}"
    grade = f" {esc(se.get('gradeText'))}" if se.get("gradeText") else ""
    lines.append(f"<b>{t('report.supplierEval')}{score}{grade}</b>")
    dims_in: list[Any] = se.get("dimensions") or []
    dims: list[dict[str, Any]] = [x for x in dims_in if _dim_block(x)]
    for dim in sorted(dims, key=_is_bad):  # ✔/— 前、✘ 后（稳定排序，不另加分组标题）
        lines.append(_dim_block(dim))
    if se.get("companyName"):
        lines.append(f"🏢 {esc(se['companyName'])}")
    if se.get("industryCluster"):
        lines.append(f"📍 {esc(se['industryCluster'])}")
    return "\n".join(lines)
