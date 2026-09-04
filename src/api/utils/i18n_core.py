"""i18n 单一真源 — 全项目语言集合 + CJK 检测。

加语言只改本文件 LANGS/AI_LANGS 两处常量；其余模块一律 import 本常量，
禁止再手写行内语言元组。完整性测试（tests/test_i18n_integrity.py）import
本文件断言三层结构，加语言漏同步 → 测试立即红。
"""

import re
from typing import Any

# 全项目支持语言（chrome-ext/lang/*.json、glossary.json、verdict_prompts.json、msg_code 共用）
LANGS: tuple[str, ...] = ("zh", "en", "vi", "th", "ru")
# 走 Qwen AI 判词的语言（zh 走 glossary 模板路径）
AI_LANGS: tuple[str, ...] = ("en", "vi", "th", "ru")

# CJK 汉字统一检测（历史多处内联正则收敛到此）
_HAS_CJK_RE = re.compile(r"[一-鿿]")


def cjk_in(text: Any) -> bool:
    """text 是否含 CJK 汉字（非 zh display 出口门禁 / 校验用）。"""
    return bool(text) and _HAS_CJK_RE.search(str(text)) is not None
