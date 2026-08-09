"""1688 URL 解析 — 纯函数，零外部依赖。

架构宪法 §九：domain 层不 import 数据库/HTTP/Config，保持纯函数可单测。
"""

import re

# 1688 商品详情页 URL 格式：detail.1688.com/offer/{数字ID}.html
_OFFER_ID_PATTERN = re.compile(r"1688\.com/offer/(\d+)")


def extract_offer_id(url: str) -> str:
    """从 1688 商品链接提取 offerId。

    Args:
        url: 1688 商品详情页 URL

    Returns:
        offerId 数字字符串，无法提取时返回空字符串

    Example:
        'https://detail.1688.com/offer/997934724655.html' → '997934724655'
        'https://m.1688.com/offer/123456.html' → '123456'
        'not-a-1688-url' → ''
    """
    m = _OFFER_ID_PATTERN.search(url)
    return m.group(1) if m else ""


def is_valid_1688_url(url: str) -> bool:
    """检查是否为有效的 1688 商品详情页链接。"""
    return bool(_OFFER_ID_PATTERN.search(url))
