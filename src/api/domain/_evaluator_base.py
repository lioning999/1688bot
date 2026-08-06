"""Evaluator 共享工具 + 阈值常量。

零外部依赖，被 _evaluator_product / _evaluator_supplier 共用。
"""
from typing import Any


def _verdict(key: str, **params: Any) -> dict[str, Any]:
    """构建判词输出：{key, params} dict。

    key 对应 term_glossary.json 中的条目，display_builder 负责查表 + 参数替换。
    """
    return {"key": key, "params": params}


def _safe_int(val: Any) -> int | None:
    """安全转 int。None / 非数字 → None。"""
    if val is None:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _safe_float(val: Any) -> float | None:
    """安全转 float。None / 非数字 → None。"""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ====================================================================
# 阈值常量（硬编码，无配置文件）
# ====================================================================

SOLD_HOT = 1000
SOLD_POTENTIAL = 100
REPURCHASE_HIGH = 30
REPURCHASE_MID = 10
PRICE_LOW = 20
PRICE_MID = 50
MOQ_LOW = 10
MOQ_MID = 100
POSITIVE_HIGH = 98
POSITIVE_MID = 95
POSITIVE_BAD = 80
WANTED_HIGH = 100
WANTED_MID = 30
SHOP_OLD = 3
SHOP_NEW = 1
