"""1688 商品分析 API — 异步轮询模式。

覆盖风险清单：
  #9  用户输入非 1688 链接 → 前后端双重校验
  #10  异步轮询 → POST 启任务 + GET 轮询状态
  #11  用户猛点按钮 → 前端 disabled + 后端请求合并
  #14  L1 前端按钮防重（后端配合：同 offer_id 未完成任务返回已有 task_id）
"""

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, field_validator

from config import Config
from domain import cache as analysis_cache, rate_limiter
from domain.quota import check_quota
from domain.urls import extract_offer_id, is_valid_1688_url
from services.analyze_svc import build_result_with_display, analyze_service
from utils.exceptions import ValidationError, InsufficientQuotaError, ResourceNotFoundError, AppError
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


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
        raise ValidationError(message="无法从链接中提取有效的商品 ID", msg_code="OFFER_ID_NOT_FOUND")
    if len(offer_id) < 8:
        raise ValidationError(message="商品 ID 格式不正确", msg_code="OFFER_ID_INVALID")

    # ---- 2. 全局限流（风险 #14 L3） ----
    if not await rate_limiter.check():
        logger.warning(f"Global rate limit hit from IP={request.client.host if request.client else '?'}")
        raise InsufficientQuotaError(
            resource_type="系统繁忙",
            msg_code="GLOBAL_RATE_LIMIT",
            details={"retry_after": "60秒"},
        )

    # ---- 3. 缓存前置：命中直接返回 task_id，不扣配额 ----
    cached: dict[str, Any] | None = analysis_cache.get(offer_id)
    if cached:
        logger.info(f"[汇总] offer_id={offer_id} 缓存命中 | 配额0 Apify✗ Qwen✗")
        result: dict[str, Any] = await build_result_with_display(cached, offer_id, body.lang)
        task_id: str = analyze_service.create_done_task(result)
        return {"code": 200, "msg_code": "OK", "data": {"task_id": task_id, "status": "pending"}, "message": "ok"}

    # ---- 4. 每日配额（未登录按 IP 3 次/天，登录按 user_id 10 次/天） ----
    user_id: int = getattr(request.state, "user_id", 0) or 0
    if user_id:
        daily_limit: int = Config.APIFY_DAILY_LOGIN_LIMIT
        quota_key: str = f"user:{user_id}"
    else:
        daily_limit = Config.APIFY_DAILY_FREE_LIMIT
        quota_key = request.client.host if request.client else "unknown"

    if not check_quota(quota_key, daily_limit):
        tip: str = "登录后可获得 10 次/天" if not user_id else "请明天再试或联系 WhatsApp"
        raise InsufficientQuotaError(
            resource_type="今日分析次数",
            msg_code="DAILY_QUOTA_EXCEEDED",
            details={"daily_limit": daily_limit, "tip": tip},
        )

    # ---- 5. 启动后台分析 ----
    task_id = await analyze_service.start(offer_id=offer_id, user_id=user_id, raw_url=body.url, lang=body.lang, quota_key=quota_key)
    logger.info(f"[汇总] offer_id={offer_id} task_id={task_id} 启动Apify | lang={body.lang or 'zh'}")

    return {
        "code": 200,
        "msg_code": "OK",
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
        raise ResourceNotFoundError(resource_type="任务", resource_id=task_id, msg_code="TASK_NOT_FOUND")

    # 任务失败 → 返回 200（保持轮询契约），msg_code 嵌入 task 数据
    if task.get("status") == "failed":
        return {
            "code": 200,
            "msg_code": task.get("error_msg_code", "INTERNAL_ERROR"),
            "data": task,
            "message": task.get("error", "分析失败"),
        }

    return {
        "code": 200,
        "msg_code": "OK",
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
        raise AppError(message="请先登录", code="LOGIN_REQUIRED", msg_code="LOGIN_REQUIRED",
                       http_status=401)

    result = await analyze_service.save_report(user_id=user_id, offer_id=body.offer_id)
    if result is None:
        # 缓存已过期
        logger.warning(f"[Save] 缓存过期 offer_id={body.offer_id} user_id={user_id}")
        raise AppError(message="分析已过期，请重新搜索该商品", code="ANALYSIS_EXPIRED",
                       msg_code="ANALYSIS_EXPIRED", http_status=410)

    # 检查是否已达 20 条上限（result 带 limit_exceeded 标记时）
    if result.get("limit_exceeded"):
        logger.warning(f"[Save] 保存上限 offer_id={body.offer_id} user_id={user_id}")
        raise AppError(message="已达 20 条保存上限，请先在历史记录中删除旧记录后再保存",
                       code="SAVE_LIMIT_EXCEEDED", msg_code="SAVE_LIMIT_EXCEEDED",
                       http_status=409)

    logger.info(f"[Save] 保存成功 offer_id={body.offer_id} user_id={user_id}")
    return {
        "code": 200,
        "msg_code": "SAVE_OK",
        "data": {"saved": True},
        "message": "已保存到我的分析",
    }
