"""每日配额计数器 — 按 key（IP 或 user:ID）限制每日分析次数。

纯函数 + 简单内存状态，零外部依赖。从 routes/analyze.py 抽出，
消除 route → service → route 循环依赖。
"""

import time

from utils.logger import get_logger

logger = get_logger(__name__)

_daily_counter: dict[str, tuple[int, float]] = {}


def check_quota(key: str, limit: int) -> bool:
    """检查配额。返回 True = 允许，False = 已用完。"""
    now = time.time()
    # 每 10 次调用清理过期条目（48h+ 未活跃），防止内存泄漏（Bug #8）
    if len(_daily_counter) % 10 == 0:
        expired = [k for k, v in _daily_counter.items() if (now - v[1]) > 172800]
        for k in expired:
            del _daily_counter[k]
    entry = _daily_counter.get(key)
    if entry is None or (now - entry[1]) > 86400:
        _daily_counter[key] = (1, now)
        logger.info(f"[配额] key={key} 首次使用 1/{limit}")
        return True
    count, first_ts = entry
    if count >= limit:
        logger.warning(f"[配额] key={key} 已用完 {count}/{limit}")
        return False
    _daily_counter[key] = (count + 1, first_ts)
    logger.info(f"[配额] key={key} 使用 {count + 1}/{limit}")
    return True


def refund(key: str) -> None:
    """Apify 失败时退还配额（成功扣、失败不扣）。"""
    entry = _daily_counter.get(key)
    if entry and entry[0] > 0:
        _daily_counter[key] = (entry[0] - 1, entry[1])

