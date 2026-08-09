"""滑动窗口全局限流 — 30 次/分钟（所有用户合计）。

覆盖风险清单：
  #14 L3 全局限流 → 脚本攻击兜底
  Bug #9 异步安全 → asyncio.Lock 保护非原子操作
"""

import asyncio
import time
from collections import deque

from config import Config

_timestamps: deque[float] = deque()
_lock: asyncio.Lock = asyncio.Lock()


async def check() -> bool:
    """检查是否在速率限制内。True = 放行, False = 超限。

    调用时机：每次 POST /api/analyze 到达时。
    正常用户 1 分钟搜 30 次不可能——只有脚本才会触发。
    """
    async with _lock:
        now = time.time()
        while _timestamps and now - _timestamps[0] > Config.RATE_LIMIT_WINDOW:
            _timestamps.popleft()
        if len(_timestamps) >= Config.RATE_LIMIT_MAX:
            return False
        _timestamps.append(now)
        return True
