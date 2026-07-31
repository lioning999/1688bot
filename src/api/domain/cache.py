"""offer_id 内存缓存 — TTL 30min, LRU 淘汰, 500 条上限。

覆盖风险清单：
  #1  同链接重复调用 → 缓存命中直接返回
  #14 L2 防刷缓存层 → 30min TTL 防高频刷同一商品
  Bug #25 LRU O(1) → OrderedDict 替代 dict + min() 全量扫描
"""

import time
from collections import OrderedDict
from typing import Any

# {offer_id: (timestamp, data)}
cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
MAX_SIZE = 500
TTL = 43200  # 12 小时


def get(offer_id: str) -> dict[str, Any] | None:
    """查缓存。命中且未过期返回数据，过期自动清理。"""
    entry = cache.get(offer_id)
    if entry is None:
        return None
    ts, data = entry
    if time.time() - ts < TTL:
        cache.move_to_end(offer_id)  # 更新访问时间（LRU）
        return data
    # 过期清理
    del cache[offer_id]
    return None


def get_expired(offer_id: str) -> dict[str, Any] | None:
    """读过期缓存（用于降级兜底）。不清理条目，留给调用方决定是否使用。"""
    entry = cache.get(offer_id)
    if entry is None:
        return None
    ts, data = entry
    if time.time() - ts >= TTL:
        return data
    return None


def set(offer_id: str, data: dict[str, Any]) -> None:
    """写缓存。超上限时 O(1) 淘汰最老条目（OrderedDict FIFO 顺序）。"""
    if offer_id in cache:
        cache.move_to_end(offer_id)
    elif len(cache) >= MAX_SIZE:
        cache.popitem(last=False)  # O(1) 淘汰最老条目
    cache[offer_id] = (time.time(), data)
