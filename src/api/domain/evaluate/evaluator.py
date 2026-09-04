"""双维度评判引擎 — 公开入口。

零外部依赖，零 IO，零随机。同一输入永远同一输出。

外部代码只 import 此文件：
  from domain.evaluate import evaluate_product, evaluate_supplier, evaluate_summary

内部实现拆分：
  _base.py      — 共享工具 + 阈值常量
  _product.py   — 产品 4 维（d1/d5/d3/d6）加权 → 档位 → 4 档 grade → 判词
  _supplier.py  — 供应商 5 维（d1–d5）加权，档位由身份/认证/年限骨架判定 → 判词

依据：docs/技术-评分标准与标签体系.md
"""
from typing import Any

from domain.evaluate._base import verdict
from domain.evaluate._product import evaluate_product
from domain.evaluate._supplier import evaluate_supplier

# 公开 API（被 display_builder.py 使用）
__all__ = ["evaluate_product", "evaluate_supplier", "evaluate_summary"]


# ====================================================================
# 综合评判 — 矩阵查找
# ====================================================================

# 产品档 × 供应商档 → 综合档
# 产品档: go / trial / caution / watch / fatal / skip
# 供应商档: trust / usable / caution / fatal / skip
SUMMARY_MATRIX: dict[str, dict[str, str]] = {
    "go": {
        "trust": "go_both", "usable": "go_product_ok",
        "caution": "conditional_supplier_weak",
        "fatal": "no_supplier_fatal", "skip": "wait_data",
    },
    "trial": {
        "trust": "conditional_factory_strong",
        "usable": "conditional_ok", "caution": "conditional_careful",
        "fatal": "no_supplier_fatal", "skip": "wait_data",
    },
    "caution": {
        "trust": "conditional_factory_strong",
        "usable": "conditional_ok", "caution": "conditional_careful",
        "fatal": "no_supplier_fatal", "skip": "wait_data",
    },
    "watch": {
        "trust": "wait_data", "usable": "wait_data", "caution": "wait_data",
        "fatal": "no_supplier_fatal", "skip": "wait_data",
    },
    "fatal": {
        "trust": "no_product_fatal", "usable": "no_product_fatal",
        "caution": "no_product_fatal",
        "fatal": "no_product_fatal", "skip": "no_product_fatal",
    },
    "skip": {
        "trust": "wait_data", "usable": "wait_data", "caution": "wait_data",
        "fatal": "no_supplier_fatal", "skip": "wait_data",
    },
}


def _tier_group(tier: str) -> str:
    """产品/供应商 tier → 档位组名（用于矩阵查找）。

    产品 tier：go / trial / caution / watch / fatal_badrate / skip
    供应商 tier：trust_strong2 / usable_ok / caution_weak2 / fatal_blackbox / skip
    """
    for prefix in ("go", "trial", "caution", "watch", "fatal", "trust", "usable"):
        if tier.startswith(prefix):
            return prefix
    if tier.startswith("skip"):
        return "skip"
    return "caution"


def evaluate_summary(product_result: dict[str, Any], supplier_result: dict[str, Any]) -> dict[str, Any]:
    """综合产品 + 供应商评判 → 拿样建议。

    产品档 × 供应商档 → 矩阵查找综合档。
    弱者定天花板：一方致命/跳过 → 全局否定/等一等。
    """
    p_tier: str = str(product_result.get("tier", "watch"))
    s_tier: str = str(supplier_result.get("tier", "caution"))
    p_group = _tier_group(p_tier)
    s_group = _tier_group(s_tier)

    summary_tier = SUMMARY_MATRIX.get(p_group, {}).get(s_group, "wait_data")

    # headline（4 档）+ grade（前端染色，与 headline 同档）
    if summary_tier.startswith("go_"):
        headline_kv = verdict("summary_headline_go")
        grade = "go"
    elif summary_tier.startswith("conditional_"):
        headline_kv = verdict("summary_headline_conditional")
        grade = "ok"
    elif summary_tier.startswith("no_"):
        headline_kv = verdict("summary_headline_no")
        grade = "bad"
    else:
        headline_kv = verdict("summary_headline_wait")
        grade = "none"

    # 综合判词证据：品侧自然数字（销量→关注→价格，取第一个有值；v2 无产品复购）
    # 厂侧好/坏信号（复用 good/bad_part_keys 机制，空也传 [] 防 format 失败）
    p_sig: dict[str, Any] = product_result.get("signals", {})
    s_sig: dict[str, Any] = supplier_result.get("signals", {})
    params: dict[str, Any] = {}

    def _fmt_num(n: Any) -> str:
        try:
            v = float(n)
            if v == int(v):
                return f"{int(v):,}"
            return f"{v:,.1f}".rstrip("0").rstrip(".")
        except (ValueError, TypeError):
            return str(n)

    def _fmt_price(v: Any) -> str:
        return f"¥{v:.2f}"

    prod_num = ""
    for field, fmt in (
        ("sold", _fmt_num),
        ("wanted", _fmt_num),
        ("display_price", _fmt_price),
    ):
        if p_sig.get(field) is not None:
            prod_num = fmt(p_sig[field])
            break
    params["prod_num"] = prod_num

    # 厂侧参数（供 good/bad part 模板的 {cert_text}/{years} 占位）
    cert_type = str(s_sig.get("cert_type", ""))
    if "·" in cert_type:
        cert_name = cert_type.rsplit("·", 1)[-1]
    else:
        cert_name = cert_type
    params["cert_text"] = cert_name.upper() if cert_name.isascii() else cert_name
    if s_sig.get("shop_years") is not None:
        params["years"] = str(s_sig["shop_years"])

    # 厂证据各取最要命的 1 个（身份→认证→年限 / 短板优先），避免综合判词冗长
    good_keys: list[str] = []
    bad_keys: list[str] = []
    for field in ("identity", "cert", "years"):
        label = s_sig.get(f"{field}_label")
        strength = s_sig.get(f"{field}_strength")
        if not label:
            continue
        if strength in ("strong", "medium") and not good_keys:
            good_keys.append(label)
        elif strength == "weak" and not bad_keys:
            bad_keys.append(label)
    params["good_part_keys"] = good_keys
    params["bad_part_keys"] = bad_keys

    summary_kv = verdict(f"summary_{summary_tier}", **params)
    reason_kv = summary_kv

    return {
        "verdict": summary_kv,
        "headline": headline_kv,
        "reason": reason_kv,
        "product_score": f"{product_result.get('score', 0)}/{product_result.get('max_score', 3.0)}",
        "supplier_score": f"{supplier_result.get('score', 0)}/{supplier_result.get('max_score', 3.0)}",
        "grade": grade,
        "tier": summary_tier,
    }
