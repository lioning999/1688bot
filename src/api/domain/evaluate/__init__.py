"""评判引擎 — 产品 4 维 + 供应商 5 维 → 加权分 + 档位 + 判词。"""
from domain.evaluate.evaluator import evaluate_product, evaluate_supplier, evaluate_summary

__all__ = ["evaluate_product", "evaluate_supplier", "evaluate_summary"]
