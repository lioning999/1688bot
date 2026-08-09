"""评判引擎 — 产品 6 维 + 供应商 3 维 → tier + 判词。"""
from domain.evaluate.evaluator import evaluate_product, evaluate_supplier, evaluate_summary

__all__ = ["evaluate_product", "evaluate_supplier", "evaluate_summary"]
