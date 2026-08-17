"""msg_code 前后端对齐契约测试 — 机器兜底，锁住「后端/前端发的码 ⊆ 前端翻译」。

病根：加/删 msg 码靠人 grep，漏了前端翻译、或 4 语言 key 不对齐，没人红。
本测试是纯文件扫描 + JSON 解析，不 import 后端、不依赖运行环境，跑一次比对两端。

断言 3 条：
  1 后端「显式发出的码」⊆ 前端 4 语言 msg.* key（后端每个码都有翻译）
  2 前端自发码（api.js / service-worker.js）⊆ 前端 4 语言 msg.* key
  3 zh/en/vi/th 四语言 msg.* key 集合完全一致（删一个漏三个 → 红）

注意：exceptions.py 的 4 个默认值（VALIDATION_ERROR 等）是函数签名默认参数
（`msg_code: str = "X"`），从不达前端，故不扫——正则只匹配「显式发出」的语法。
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "src" / "api"
EXT_DIR = ROOT / "src" / "chrome-ext"
LANG_DIR = EXT_DIR / "lang"
LANGS = ("zh", "en", "vi", "th")

# 后端「显式发出」的 3 种语法（均双引号字符串字面量；排除默认参数 `msg_code: str = "X"`）
_BACKEND_PATTERNS = (
    re.compile(r'msg_code="([A-Z0-9_]+)"'),             # raise AppError(msg_code="X")
    re.compile(r'"msg_code":\s*"([A-Z0-9_]+)"'),        # return {"msg_code": "X"}
    re.compile(r'"error_msg_code":\s*"([A-Z0-9_]+)"'),  # task dict {"error_msg_code": "X"}
)

# 前端自发码（对象字面量 msg_code: 'X' / msg_code: "X"）
_FRONTEND_PATTERN = re.compile(r"msg_code\s*[:=]\s*['\"]([A-Z0-9_]+)['\"]")
_FRONTEND_SOURCES = (EXT_DIR / "lib" / "api.js", EXT_DIR / "service-worker.js")


def _backend_codes() -> set[str]:
    codes: set[str] = set()
    for py in API_DIR.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for pat in _BACKEND_PATTERNS:
            codes.update(pat.findall(text))
    return codes


def _frontend_codes() -> set[str]:
    codes: set[str] = set()
    for js in _FRONTEND_SOURCES:
        if js.exists():
            codes.update(_FRONTEND_PATTERN.findall(js.read_text(encoding="utf-8")))
    return codes


def _lang_keys(lang: str) -> set[str]:
    data = json.loads((LANG_DIR / f"{lang}.json").read_text(encoding="utf-8"))
    return {k[len("msg."):] for k in data if k.startswith("msg.")}


def _missing(codes: set[str]) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for lang in LANGS:
        miss = codes - _lang_keys(lang)
        if miss:
            missing[lang] = sorted(miss)
    return missing


def test_backend_codes_have_all_translations():
    """后端每个显式发出的码，4 语言都必须有 msg.* 翻译。"""
    missing = _missing(_backend_codes())
    assert not missing, f"后端码缺翻译: {missing}"


def test_frontend_codes_have_all_translations():
    """前端自发码（api.js / SW）也必须 4 语言有 msg.* 翻译。"""
    missing = _missing(_frontend_codes())
    assert not missing, f"前端自发码缺翻译: {missing}"


def test_four_langs_msg_keys_aligned():
    """4 语言 msg.* key 集合完全一致，zh 为基准。"""
    zh = _lang_keys("zh")
    for lang in ("en", "vi", "th"):
        keys = _lang_keys(lang)
        assert keys == zh, (
            f"{lang} 与 zh 的 msg.* key 不一致\n"
            f"  zh 有 {lang} 无: {sorted(zh - keys)}\n"
            f"  {lang} 有 zh 无: {sorted(keys - zh)}"
        )
