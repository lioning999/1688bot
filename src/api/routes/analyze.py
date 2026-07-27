"""1688 商品分析 API — 异步轮询模式。

覆盖风险清单：
  #9  用户输入非 1688 链接 → 前后端双重校验
  #10  异步轮询 → POST 启任务 + GET 轮询状态
  #11  用户猛点按钮 → 前端 disabled + 后端请求合并
  #14  L1 前端按钮防重（后端配合：同 offer_id 未完成任务返回已有 task_id）
"""

import time
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, field_validator

from config import Config
from domain import cache as analysis_cache, rate_limiter
from domain.urls import extract_offer_id, is_valid_1688_url
from services.analyze_svc import _build_result_with_display, analyze_service
from utils.exceptions import ValidationError, InsufficientQuotaError, ResourceNotFoundError
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# 简单内存计数器（按 IP，V1 未登录用户限制）
_daily_counter: dict[str, tuple[int, float]] = {}


class AnalyzeRequest(BaseModel):
    url: str
    lang: str = ""  # 目标语言（en/vi/th/id），空字符串 = 不翻译（V1 路径）

    @field_validator("url")
    @classmethod
    def must_be_1688_detail(cls, v: str) -> str:
        """风险 #9：前后端双重校验 1688 链接格式。"""
        if not is_valid_1688_url(v):
            raise ValueError("请输入有效的 1688 商品链接（detail.1688.com/offer/...）")
        return v.strip()


# ====================================================================
# POST /api/analyze — 启动分析（异步轮询模式，风险 #10）
# ====================================================================

@router.post("/api/analyze")
async def analyze_start(body: AnalyzeRequest, request: Request) -> dict[str, Any]:
    """启动 1688 商品分析，立即返回 task_id。

    前端收到 task_id 后每 2 秒轮询 GET /api/analyze/{task_id}。
    """
    # ---- 1. 提取 offerId ----
    offer_id = extract_offer_id(body.url)
    if not offer_id or not offer_id.isdigit():
        raise ValidationError(message="无法从链接中提取有效的商品 ID")
    if len(offer_id) < 8:
        raise ValidationError(message="商品 ID 格式不正确")

    # ---- 2. 全局限流（风险 #14 L3） ----
    if not await rate_limiter.check():
        logger.warning(f"Global rate limit hit from IP={request.client.host if request.client else '?'}")
        raise InsufficientQuotaError(
            resource_type="系统繁忙",
            details={"retry_after": "60秒"},
        )

    # ---- 3. 每日配额（未登录按 IP 3 次/天，登录按 user_id 10 次/天） ----
    user_id: int = getattr(request.state, "user_id", 0) or 0
    if user_id:
        daily_limit: int = Config.APIFY_DAILY_LOGIN_LIMIT
        quota_key: str = f"user:{user_id}"
    else:
        daily_limit = Config.APIFY_DAILY_FREE_LIMIT
        quota_key = request.client.host if request.client else "unknown"

    if not _check_quota(quota_key, daily_limit):
        tip: str = "登录后可获得 10 次/天" if not user_id else "请明天再试或联系 WhatsApp"
        raise InsufficientQuotaError(
            resource_type="今日分析次数",
            details={"daily_limit": daily_limit, "tip": tip},
        )

    # ---- 3.5. 缓存前置：命中直接返回，不创建 task，不调 Apify/Qwen ----
    cached: dict[str, Any] | None = analysis_cache.get(offer_id)
    if cached:
        logger.info(f"Cache hit at route: offer_id={offer_id}")
        result: dict[str, Any] = await _build_result_with_display(cached, offer_id, body.lang)
        return {"code": 200, "data": {"status": "done", "result": result}, "message": "ok"}

    # ---- 4. 启动后台分析 ----
    task_id = await analyze_service.start(offer_id=offer_id, user_id=user_id, raw_url=body.url, lang=body.lang, quota_key=quota_key)
    logger.info(f"Analysis started: offer_id={offer_id} task_id={task_id} user_id={user_id} lang={body.lang}")

    return {
        "code": 200,
        "data": {"task_id": task_id, "status": "pending"},
        "message": "ok",
    }


# ====================================================================
# GET /api/analyze/{task_id} — 轮询状态（风险 #10）
# ====================================================================

@router.get("/api/analyze/{task_id}")
async def analyze_status(task_id: str) -> dict[str, Any]:
    """查询分析任务状态。

    返回:
      - status=pending/running → 前端继续轮询
      - status=done → result 包含完整分析数据
      - status=failed → error 包含错误信息
    """
    task = analyze_service.get_task(task_id)
    if task is None:
        raise ResourceNotFoundError(resource_type="任务", resource_id=task_id)

    return {
        "code": 200,
        "data": task,
        "message": "ok",
    }


# ====================================================================
# POST /api/save-report — 手动保存分析报告（需登录）
# ====================================================================

class SaveReportRequest(BaseModel):
    offer_id: str

    @field_validator("offer_id")
    @classmethod
    def must_be_valid(cls, v: str) -> str:
        if not v.isdigit() or len(v) < 8:
            raise ValueError("无效的 offer_id")
        return v.strip()


@router.post("/api/save-report")
async def save_report(body: SaveReportRequest, request: Request) -> dict[str, Any]:
    """用户手动保存分析报告到数据库。

    从中端缓存取数据，不需要重新调 Apify。
    需 JWT 认证（/api/ 前缀自动拦截）。
    """
    user_id: int = getattr(request.state, "user_id", 0) or 0
    if not user_id:
        return {"code": 401, "data": None, "message": "请先登录"}

    result = await analyze_service.save_report(user_id=user_id, offer_id=body.offer_id)
    if result is None:
        # 缓存已过期
        return {
            "code": 410,
            "data": None,
            "message": "分析已过期，请重新搜索该商品",
        }

    # 检查是否已达 20 条上限（result 带 limit_exceeded 标记时）
    if result.get("limit_exceeded"):
        return {
            "code": 409,
            "data": {"count": result.get("count", 20)},
            "message": "已达 20 条保存上限，请先在历史记录中删除旧记录后再保存",
        }

    logger.info(f"Report saved: offer_id={body.offer_id} user_id={user_id}")
    return {
        "code": 200,
        "data": {"saved": True},
        "message": "已保存到我的分析",
    }


# ====================================================================
# 配额工具
# ====================================================================

def _check_quota(key: str, limit: int) -> bool:
    now = time.time()
    # 每 10 次调用清理过期条目（48h+ 未活跃），防止内存泄漏（Bug #8）
    if len(_daily_counter) % 10 == 0:
        expired = [k for k, v in _daily_counter.items() if (now - v[1]) > 172800]
        for k in expired:
            del _daily_counter[k]
    entry = _daily_counter.get(key)
    if entry is None or (now - entry[1]) > 86400:
        _daily_counter[key] = (1, now)
        return True
    count, first_ts = entry
    if count >= limit:
        return False
    _daily_counter[key] = (count + 1, first_ts)
    return True


def _quota_refund(key: str) -> None:
    """Apify 失败时退还配额（成功扣、失败不扣）。"""
    entry = _daily_counter.get(key)
    if entry and entry[0] > 0:
        _daily_counter[key] = (entry[0] - 1, entry[1])
