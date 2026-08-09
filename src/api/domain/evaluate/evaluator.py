"""双维度评判引擎 — 公开入口。

零外部依赖，零 IO，零随机。同一输入永远同一输出。

外部代码只 import 此文件：
  from domain.evaluate import evaluate_product, evaluate_supplier, evaluate_summary

内部实现拆分：
  _base.py      — 共享工具 + 阈值常量
  _product.py   — 产品 6 维 → 致命检查 → 12 规则档位匹配 → 判词
  _supplier.py  — 供应商 3 维 → 黑箱检查 → 6 规则信号计数 → 判词

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
        "usable": "conditional_both_mid", "caution": "conditional_both_mid",
        "fatal": "no_supplier_fatal", "skip": "wait_data",
    },
    "caution": {
        "trust": "conditional_factory_strong",
        "usable": "conditional_both_mid", "caution": "conditional_both_mid",
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

    产品 tier 前缀 → group:
      go_* → go, trial_* → trial, caution_* → caution,
      watch_* → watch, fatal_* → fatal, skip → skip
    供应商 tier 前缀 → group:
      trust_* → trust, usable_* → usable,
      caution_* / fatal_* / skip → 对应名
    """
    for prefix in ("go_", "trial_", "caution_", "watch_", "fatal_",
                   "trust_", "usable_"):
        if tier.startswith(prefix):
            return prefix.rstrip("_")
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

    # headline（4 档）
    if summary_tier.startswith("go_"):
        headline_kv = verdict("summary_headline_go")
    elif summary_tier.startswith("conditional_"):
        headline_kv = verdict("summary_headline_conditional")
    elif summary_tier.startswith("no_"):
        headline_kv = verdict("summary_headline_no")
    else:
        headline_kv = verdict("summary_headline_wait")

    reason_kv = verdict(f"summary_{summary_tier}")

    return {
        "verdict": verdict(f"summary_{summary_tier}"),
        "headline": headline_kv,
        "reason": reason_kv,
        "product_score": f"{product_result.get('score', 0)}/{product_result.get('max_score', 15)}",
        "supplier_score": f"{supplier_result.get('score', 0)}/{supplier_result.get('max_score', 9)}",
        "tier": summary_tier,
    }
