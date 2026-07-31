"""1688 商品数据翻译 — Qwen3-Flash 翻译 1688 原始中文字段。

翻译范围：仅 1688/Apify 返回的中文数据（title/supplierName/shippingLocation/certType/rankText/factoryFlags +
specs/skus）。解释文案/判词已通过 glossary 预翻译，不在此层处理。

4 语言独立 prompt，每语言含术语表 + 禁用词表。
Prompt 配置从 translator_prompts.json 加载，改 prompt 不改代码。
纯函数 + 异步 API 调用。翻译失败不阻塞主流程，返回原始 display。

覆盖风险清单：
  - 翻译失败 → 不设 _translated，前端降级显示中文
  - 输出校验 → 白名单校验 + specs 结构验证
  - Qwen API 超时 → 8s 超时，降级不崩溃
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any, cast

from adapters.qwen_adapter import qwen_adapter
from config import Config
from utils.logger import get_logger

logger = get_logger(__name__)

# ---- 加载 prompt 配置 ----
_PROMPTS_PATH = Path(__file__).parent / "translator_prompts.json"
with open(_PROMPTS_PATH, "r", encoding="utf-8") as _f:
    _P = json.load(_f)

# ---- 加载术语表（与 display_builder.py 共享同一数据源） ----
_GLOSSARY_PATH = Path(__file__).parent / "term_glossary.json"
with open(_GLOSSARY_PATH, "r", encoding="utf-8") as _f:
    _GL = json.load(_f)

# 从 JSON 推导支持的语言列表
_LANG_NAMES: dict[str, str] = {
    code: _P["languages"][code]["name"]
    for code in _P["languages"]
}

# Path 3 需要翻译的字段白名单。只留 1688 原始数据，解释文案/判词/tier/industry 已走 glossary。
_TRANSLATABLE_SCALAR: list[str] = [
    "title",
    "supplierName", "shippingLocation", "factoryFlags",
    "certType", "rankText",
]
_TRANSLATABLE_LIST: list[str] = ["specs", "skus"]

# 白名单字段名 → 子对象中的实际键名。
# 改 _TRANSLATABLE_SCALAR / _TRANSLATABLE_LIST → 必须同步改此表。
_KEY_IN_SOURCE: dict[str, str] = {
    # 顶层（display.{key}）
    "title":            "title",
    # factory 子对象
    "supplierName":     "supplierName",
    "shippingLocation": "shippingLocation",
    "factoryFlags":     "factoryFlags",
    "certType":         "certType",
    "rankText":         "rankText",
}

# Qwen API 超时
_TRANSLATE_TIMEOUT: float = 20.0

# 类型哨兵：避免 or {} 引入 dict[Unknown, Unknown]
_EMPTY: dict[str, Any] = {}


# ====================================================================
# 公开接口
# ====================================================================


async def translate_display(display: dict[str, Any], lang: str) -> dict[str, Any]:
    """翻译 display JSON 中的 Path 3 中文字段。

    Args:
        display: build_display() 输出的 display JSON
        lang: 目标语言代码（en/vi/th/id）

    Returns:
        同一 display dict，Path 3 字段已翻译。翻译失败时原样返回。
    """
    if lang not in _LANG_NAMES:
        logger.debug(f"[翻译] 跳过: lang={lang} 不在支持列表 {list(_LANG_NAMES)}")
        return display
    if not Config.QWEN_API_KEY:
        logger.warning("[翻译] 跳过: QWEN_API_KEY 未配置")
        return display

    # 提取待翻译的 Path 3 字段
    input_obj: dict[str, Any] = _extract_translatable(display)
    if not input_obj:
        logger.info(f"[翻译] lang={lang} 无待翻译字段（Path 3 为空或已是目标语言）")
        return display

    # 前置替换：glossary 已知术语在送 Qwen 之前直接替换，减少 prompt token
    input_obj = _pre_replace_glossary(input_obj, lang)

    t0 = time.time()
    try:
        scalar_keys = [k for k in input_obj if k not in ("specs", "skus")]
        spec_count = len(input_obj.get("specs", []))
        sku_count = len(input_obj.get("skus", []))
        logger.info(
            f"[翻译] 开始 Qwen 翻译 lang={lang} "
            f"标量字段={len(scalar_keys)}{scalar_keys if scalar_keys else ''} "
            f"specs={spec_count}条 skus={sku_count}条"
        )
        translated = await _call_qwen(input_obj, lang)
        if not translated:
            # Qwen 偶发 malformed JSON — 等 1 秒重试 1 次
            logger.warning(f"[翻译] 第1次失败 lang={lang}，1秒后重试...")
            await asyncio.sleep(1)
            translated = await _call_qwen(input_obj, lang)
        t_qwen = time.time()
        if translated:
            _merge_translated(display, translated)
            display["_translatedLang"] = lang
            logger.info(
                f"[翻译] ✓ 成功 lang={lang} "
                f"耗时 total={t_qwen - t0:.1f}s "
                f"翻译字段数={len(translated)}/{len(input_obj)}"
            )
        else:
            logger.warning(
                f"[翻译] ✗ Qwen 返回空 lang={lang} "
                f"耗时={time.time() - t0:.1f}s — 降级显示中文原文"
            )
    except Exception:
        logger.exception(
            f"[翻译] ✗ 异常 lang={lang} "
            f"耗时={time.time() - t0:.1f}s — 降级显示中文原文"
        )

    return display


# ====================================================================
# 内部：提取 / 合并
# ====================================================================


def _extract_translatable(display: dict[str, Any]) -> dict[str, Any]:
    """从 display JSON 提取 Path 3 字段，扁平化为 Qwen 输入。

    遍历范围：顶层 + trustBar / sales / factory 三个子对象 + specs/skus 两个数组。
    自动检查：发现含中文但不在白名单的字段 → logger.warning。
    """
    result: dict[str, Any] = {}

    # 嵌套子对象
    factory: dict[str, Any] = display.get("factory") or _EMPTY
    trust: dict[str, Any] = display.get("trustBar") or _EMPTY
    sales: dict[str, Any] = display.get("sales") or _EMPTY

    # ---- 自动检查：扫描所有叶子节点，发现含中文但不在白名单的字段 ----
    _check_chinese_not_in_whitelist(display, factory, sales, trust)

    for key in _TRANSLATABLE_SCALAR:
        source_key: str = _KEY_IN_SOURCE.get(key, key)
        # 优先级：顶层 → factory → sales → trustBar
        for source in (display, factory, sales, trust):
            val: Any = source.get(source_key)
            if val and isinstance(val, str) and _contains_chinese(val):
                result[key] = val
                break

    # specs / skus 列表。skus 只取前 5 个（控制 Qwen 输出长度，其余去 1688 原链接看）。
    SKU_MAX = 5
    for list_key in _TRANSLATABLE_LIST:
        items: Any = display.get(list_key)
        if items and isinstance(items, list):
            filtered: list[dict[str, str]] = []
            for item in items:  # type: ignore[reportUnknownVariableType]
                if isinstance(item, dict):
                    name: str = str(item.get("name", ""))  # type: ignore[reportUnknownMemberType,reportUnknownArgumentType]
                    value: str = str(item.get("value", ""))  # type: ignore[reportUnknownMemberType,reportUnknownArgumentType]
                    if _contains_chinese(name) or _contains_chinese(value):
                        filtered.append({"name": name, "value": value})
            if list_key == "skus" and len(filtered) > SKU_MAX:
                logger.info(f"[翻译] SKU 过多 {len(filtered)}→{SKU_MAX}，截断")
                filtered = filtered[:SKU_MAX]
            if filtered:
                result[list_key] = filtered

    return result


def _merge_translated(display: dict[str, Any], translated: dict[str, Any]) -> None:
    """将翻译结果合并回 display JSON。"""
    factory: dict[str, Any] = display.get("factory") or _EMPTY
    trust: dict[str, Any] = display.get("trustBar") or _EMPTY
    sales: dict[str, Any] = display.get("sales") or _EMPTY

    for key, val in translated.items():
        if key in ("specs", "skus"):
            # 数组字段：按索引合并 name/value
            orig_list: list[dict[str, Any]] = display.get(key) or []
            for i, item in enumerate(val):
                if i < len(orig_list):
                    orig_list[i]["name"] = item.get("name", orig_list[i].get("name", ""))
                    if "value" in item:
                        orig_list[i]["value"] = item.get("value", orig_list[i].get("value", ""))
            continue
        # 标量字段：优先级 顶层 → factory → sales → trustBar
        source_key: str = _KEY_IN_SOURCE.get(key, key)
        if key in display:
            display[key] = val
        elif source_key in factory:
            factory[source_key] = val
        elif source_key in sales:
            sales[source_key] = val
        elif source_key in trust:
            trust[source_key] = val


# ====================================================================
# 内部：Qwen API 调用
# ====================================================================


def _contains_chinese(text: str) -> bool:
    """检查文本是否包含中文字符。"""
    return any("一" <= ch <= "鿿" for ch in text)


def _check_chinese_not_in_whitelist(
    display: dict[str, Any],
    factory: dict[str, Any],
    sales: dict[str, Any],
    trust: dict[str, Any],
) -> None:
    """扫描 display 所有叶子节点，含中文但不在白名单 → logger.warning。"""
    whitelist_scalar: set[str] = set(_TRANSLATABLE_SCALAR)
    whitelist_all: set[str] = set(_TRANSLATABLE_SCALAR + _TRANSLATABLE_LIST)

    # 反向映射：子对象实际 key → 白名单 key
    _reverse_source: dict[str, str] = {v: k for k, v in _KEY_IN_SOURCE.items()}

    # 显式排除的字段（不需翻译）
    _excluded: set[str] = {"titleOrig"}

    sub_objects: list[tuple[dict[str, Any], str]] = [
        (factory, "factory"),
        (sales, "sales"),
        (trust, "trustBar"),
    ]

    # 顶层标量
    for key, val in display.items():
        if key in _excluded or key in ("factory", "trustBar", "sales", "specs", "skus", "_translatedLang"):
            continue
        if isinstance(val, str) and _contains_chinese(val) and key not in whitelist_scalar:
            logger.warning(f"display.{key} contains Chinese but not in translator whitelist")

    # 子对象标量
    for sub, name in sub_objects:
        for key, val in sub.items():
            if not isinstance(val, str) or not _contains_chinese(val):
                continue
            # 检查反向映射：子对象中的实际 key → 白名单 key
            whitelist_key: str = _reverse_source.get(key, key)
            if whitelist_key not in whitelist_all:
                logger.warning(f"display.{name}.{key} contains Chinese but not in translator whitelist")


def _pre_replace_glossary(input_obj: dict[str, Any], lang: str) -> dict[str, Any]:
    """前置替换：在送 Qwen 之前，用 glossary 替换已知中文术语。

    只取 key 含中文且非格式串的简单术语（排除 verdict_/explain_/industry_ 等）。
    长词优先排序，避免 "工厂" 先于 "超级工厂" 匹配。
    """
    _SKIP_PREFIXES: tuple[str, ...] = (
        "trust_", "sales_", "badge_", "verdict_", "explain_",
        "emoji_", "unit_", "industry_", "tier_", "star_",
    )
    terms: list[tuple[str, str]] = []  # [(中文, 译文), ...]
    for zh, entry in _GL.items():
        if zh.startswith("_") or not isinstance(entry, dict):
            continue
        if not _contains_chinese(zh):
            continue
        if any(zh.startswith(p) for p in _SKIP_PREFIXES):
            continue
        d: dict[str, str] = cast(dict[str, str], entry)
        en_value: str = d.get("en") or zh
        translation: str = d.get(lang) or en_value
        if translation and translation != zh:
            terms.append((zh, translation))

    if not terms:
        return input_obj

    # 长词优先：超级工厂 > 工厂
    terms.sort(key=lambda x: -len(x[0]))

    result: dict[str, Any] = {}
    for key, val in input_obj.items():
        result[key] = _replace_terms(val, terms)
    return result


def _replace_terms(val: Any, terms: list[tuple[str, str]]) -> Any:
    """对值执行长词优先的 str.replace。递归处理 list/dict。"""
    if isinstance(val, str):
        for zh, trans in terms:
            val = val.replace(zh, trans)
        return val
    if isinstance(val, list):
        return [_replace_terms(item, terms) for item in cast(list[Any], val)]
    if isinstance(val, dict):
        return {k: _replace_terms(v, terms) for k, v in cast(dict[str, Any], val).items()}
    return val


async def _call_qwen(input_obj: dict[str, Any], lang: str) -> dict[str, Any] | None:
    """调用 Qwen3-Flash API 翻译 JSON。成功返回翻译后 dict，失败返回 None。"""
    lang_data: dict[str, Any] = _P["languages"][lang]
    lang_name: str = lang_data["name"]
    input_json = json.dumps(input_obj, ensure_ascii=False)
    input_bytes = len(input_json.encode("utf-8"))

    prompt = _P["template"].format(
        lang_name=lang_name,
        forbidden=lang_data["forbidden"],
        input_json=input_json,
    )

    t_call = time.time()
    body = await qwen_adapter.chat(
        messages=[
            {"role": "system", "content": _P["system"]},
            {"role": "user", "content": prompt},
        ],
        model=Config.QWEN_MODEL,
        api_key=Config.QWEN_API_KEY,
        api_base=Config.QWEN_API_BASE,
        timeout=_TRANSLATE_TIMEOUT,
    )
    t_resp = time.time()

    if body is None:
        logger.warning(f"[翻译] Qwen API 返回 None lang={lang} 耗时={t_resp - t_call:.1f}s")
        return None

    content: str = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    usage = body.get("usage", {})

    if not content:
        logger.warning(f"[翻译] Qwen 返回空 content lang={lang} 耗时={t_resp - t_call:.1f}s")
        return None

    result = _parse_and_validate(content, input_obj)
    t_parse = time.time()
    if result:
        logger.info(
            f"[翻译] Qwen API 调用完成 lang={lang} "
            f"耗时 api={t_resp - t_call:.1f}s parse={t_parse - t_resp:.1f}s "
            f"输入={input_bytes}B 输出={len(content.encode('utf-8'))}B "
            f"tokens in={usage.get('prompt_tokens','?')} out={usage.get('completion_tokens','?')}"
        )
    else:
        logger.warning(f"[翻译] Qwen 返回 JSON 解析/校验失败 lang={lang} content前200字符={content[:200]}")
    return result


# ====================================================================
# 内部：JSON 解析 + 校验
# ====================================================================


def _parse_and_validate(content: str, input_obj: dict[str, Any]) -> dict[str, Any] | None:
    """解析 LLM 返回的 JSON 并校验结构与键白名单。"""
    content = content.strip()
    # 去掉可能的 markdown 包裹
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        result: dict[str, Any] = json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning(
            f"[翻译] Qwen 返回 JSON 解析失败: {e} "
            f"content尾100字符={content[-100:]} "
            f"content总长={len(content)}"
        )
        return None

    # 白名单校验：不允许新增键
    input_keys: set[str] = set(input_obj.keys())  # type: ignore[reportUnknownArgumentType]
    result_keys: set[str] = set(result.keys())  # type: ignore[reportUnknownArgumentType]
    extra = result_keys - input_keys
    if extra:
        logger.warning(f"Qwen added unexpected keys: {extra}")
        result = {k: v for k, v in result.items() if k in input_keys}

    # 校验 specs 结构
    if "specs" in result and "specs" in input_obj:
        if not isinstance(result["specs"], list):
            logger.warning("Qwen returned specs as non-list, discarding")
            del result["specs"]
        else:
            valid_specs: list[dict[str, str]] = []
            orig_specs: list[dict[str, Any]] = input_obj["specs"]
            specs_raw: list[Any] = result["specs"]  # type: ignore[reportUnknownVariableType]
            for i, s in enumerate(specs_raw):
                if isinstance(s, dict) and "name" in s and "value" in s:
                    valid_specs.append({"name": str(s["name"]), "value": str(s["value"])})  # type: ignore[reportUnknownArgumentType]
                else:
                    # 回退到原始值
                    if i < len(orig_specs):
                        orig = orig_specs[i]
                        valid_specs.append({"name": str(orig.get("name", "")), "value": str(orig.get("value", ""))})
            result["specs"] = valid_specs

    return result
