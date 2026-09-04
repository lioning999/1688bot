"""i18n 结构完整性测试 — 锁「翻译一次成型，加语言不再复发」。

三层结构各配一道结构锁（纯查文件，不跑流程，秒级）：
  ① 壳    : chrome-ext/lang/*.json 文件集合 + currency.symbol 5 语言齐
             （msg.* key 对齐另由 test_msg_align.py 锁，本文件不重复）
  ② 字典  : glossary.json 值结构 == LANGS；键不得含中文（58 键待批 B ASCII 化 → 转绿）
  ③ Qwen  : verdict_prompts.json 顶层覆盖 AI_LANGS + conclusion_words/urgency 全语言

所有断言 import LANGS/AI_LANGS（src/api/utils/i18n_core.py 单一真源）——
加语言只改那一处注册 + 各语言文件，本文件即自动给出红/绿结果。
"""

import json
from pathlib import Path

from utils.i18n_core import LANGS, AI_LANGS, cjk_in

ROOT = Path(__file__).resolve().parent.parent
_GLOSSARY = ROOT / "src/api/domain/data/glossary.json"
_VP = ROOT / "src/api/domain/display/verdict_prompts.json"
_LANG_DIR = ROOT / "src/chrome-ext/lang"


def _glossary() -> dict:
    return json.loads(_GLOSSARY.read_text(encoding="utf-8"))


def _lang_data(lang: str) -> dict:
    return json.loads((_LANG_DIR / f"{lang}.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ #
# ② 字典 — glossary
# ------------------------------------------------------------------ #
def test_glossary_value_langs_exactly_LANGS():
    """每个词条值 dict 语言键 == LANGS；漏一门 → 该词条降级中文/缺失。"""
    for key, val in _glossary().items():
        if key in ("_about", "_aliases"):
            continue
        assert isinstance(val, dict), f"词条 {key} 不是 dict"
        diff = set(val) ^ set(LANGS)
        assert not diff, f"词条 {key} 语言键不一致: 多/少 {sorted(diff)}"


def test_glossary_keys_no_cjk():
    """字典键必须是 ASCII 中性代号，禁止中文当键。"""
    bad = [k for k in _glossary() if cjk_in(k)]
    assert not bad, f"{len(bad)} 个键含中文: {bad[:10]}"


def test_glossary_aliases_valid():
    """_aliases 过渡表自洽：键 = 旧中文键（已不存顶层），值 = 存在的 ASCII 键。

    迁移期旧引用靠它兜底翻译；旧引用全部清完后删本表。
    """
    gl = _glossary()
    aliases = gl.get("_aliases")
    assert isinstance(aliases, dict) and aliases, "_aliases 缺失/为空"
    stale = [k for k in aliases if k in gl]
    assert not stale, f"旧中文键仍存顶层（迁移残留）: {stale[:10]}"
    bad_old = [k for k in aliases if not cjk_in(k)]
    assert not bad_old, f"别名键非中文旧键: {bad_old}"
    bad_val = [v for v in aliases.values() if cjk_in(v) or v not in gl]
    assert not bad_val, f"别名指向非 ASCII/不存在键: {bad_val[:10]}"


# ------------------------------------------------------------------ #
# ③ Qwen — verdict_prompts
# ------------------------------------------------------------------ #
def test_verdict_prompts_ai_langs_covered():
    """prompt 顶层 + 结论词/紧迫词表必须覆盖 AI_LANGS（加 AI 语言漏 prompt → 红）。"""
    vp = json.loads(_VP.read_text(encoding="utf-8"))
    missing_top = [l for l in AI_LANGS if l not in vp]
    assert not missing_top, f"verdict_prompts.json 缺语言顶层: {missing_top}"
    for lang in AI_LANGS:
        sys_txt = (vp.get(lang) or {}).get("system", "")
        assert isinstance(sys_txt, str) and sys_txt.strip(), f"{lang} system prompt 为空"
    for section in ("conclusion_words", "urgency_patterns"):
        langs = (vp.get("_structure") or {}).get(section, {})
        missing = [l for l in AI_LANGS if l not in langs]
        assert not missing, f"_structure.{section} 缺语言: {missing}"


# ------------------------------------------------------------------ #
# ① 壳 — chrome-ext lang JSON
# ------------------------------------------------------------------ #
def test_chrome_lang_files_match_LANGS():
    """lang/*.json 文件集合 == LANGS；多出一个语言文件而没注册 LANGS → 红。"""
    have = {p.stem for p in _LANG_DIR.glob("*.json")}
    diff = set(have) ^ set(LANGS)
    assert not diff, f"lang 文件与 LANGS 不一致: 多/少 {sorted(diff)}"


def test_chrome_lang_currency_symbol_all_langs():
    """壳 lang JSON 货币符号 5 语言齐（ru ₽ 曾被漏测）。"""
    for lang in LANGS:
        sym = _lang_data(lang).get("currency.symbol", "")
        assert isinstance(sym, str) and sym.strip(), f"lang/{lang}.json currency.symbol 缺失/为空"
