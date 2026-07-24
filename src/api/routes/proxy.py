"""图片代理路由 — 解决 1688 CDN 不返回 CORS 头导致 html2canvas 无法导出图片的问题。"""

from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# 只允许代理 1688 图片 CDN，防止被滥用为开放代理
# Bug #20：加后缀匹配，1688 新增 CDN 域名自动放行
ALLOWED_HOSTS = {
    "cbu01.alicdn.com",
    "img.alicdn.com",
    "gdp.alicdn.com",
    "gw.alicdn.com",
    "img.alibaba.com",
}
_ALLOWED_SUFFIXES = (".alicdn.com", ".alibaba.com")

# 1688 CDN 有防盗链检查，需要带 Referer
PROXY_HEADERS = {
    "Referer": "https://detail.1688.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


@router.get("/api/proxy/image")
async def proxy_image(url: str = Query(..., description="需要代理的图片完整 URL")):
    """代理获取远程图片，返回二进制流。用于 html2canvas 截图时绕过 CORS 限制。"""
    host = urlparse(url).hostname or ""
    if host not in ALLOWED_HOSTS and not any(host.endswith(s) for s in _ALLOWED_SUFFIXES):
        raise HTTPException(status_code=403, detail=f"不允许代理该域名: {host}")

    try:
        async with httpx.AsyncClient(timeout=15, headers=PROXY_HEADERS, http2=False) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning(f"图片代理失败: {url[:80]} — {e}")
        raise HTTPException(status_code=502, detail="图片获取失败")

    content_type = resp.headers.get("content-type", "image/jpeg")
    return Response(content=resp.content, media_type=content_type)
