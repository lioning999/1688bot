"""i18n — 合并 bot 专属文案 + 共享 msg.* 翻译。

msg.* 是后端→前端错误码契约，唯一翻译来源 = chrome-ext/lang/ru.json（铁律九）。
bot 只读不写，避免双份翻译漂移。bot 专属键覆盖（加 emoji 等）。
"""

import json
from pathlib import Path

_BOT_DIR = Path(__file__).resolve().parent
_SHARED = json.load(open(_BOT_DIR.parent / "chrome-ext" / "lang" / "ru.json", encoding="utf-8"))
_BOT = json.load(open(_BOT_DIR / "lang" / "ru.json", encoding="utf-8"))

_T: dict[str, str] = {}
_T.update(_SHARED)   # 先加载共享（msg.* 等）
_T.update(_BOT)      # bot 专属覆盖


def t(key: str, **kwargs: object) -> str:
    """查文案；缺键返回 key 本身（宁可露出 key 也不乱猜）。支持 {n} 占位。"""
    text = _T.get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text
