"""i18n — bot 专属文案，自包含（不再读 chrome-ext）。

msg.*（后端错误码）在 bot/lang/ru.json 内置一份与 chrome-ext 共享同值；
两端一致性由 tests/test_msg_align.py 锁对齐，改一处须同步另一处。
"""

import json
from pathlib import Path

_BOT_DIR = Path(__file__).resolve().parent
_T: dict[str, str] = json.load(open(_BOT_DIR / "lang" / "ru.json", encoding="utf-8"))


def t(key: str, **kwargs: object) -> str:
    """查文案；缺键返回 key 本身（宁可露出 key 也不乱猜）。支持 {n} 占位。"""
    text = _T.get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text
