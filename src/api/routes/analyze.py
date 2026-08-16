"""1688 商品分析 API — 异步轮询模式。

覆盖风险清单：
  #9  用户输入非 1688 链接 → 前后端双重校验
  #10  异步轮询 → POST 启任务 + GET 轮询状态
  #11  用户猛点按钮 → 前端 disabled + 后端请求合并
  #14  L1 前端按钮防重（后端配合：同 offer_id 未完成任务返回已有 task_id）
"""

import re
import time
from datetime import date
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, field_validator

from config import Config
from domain.infra import rate_limiter
from domain.infra.urls import extract_offer_id, is_valid_1688_url
from repositories.user_repo import UserRepository
from services.analyze_svc import analyze_service
from utils.exceptions import ValidationError, InsufficientQuotaError, ResourceNotFoundError, AppError
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


class AnalyzeRequest(BaseModel):
    url: str
    lang: str = ""  # 目标语言（en/vi/th/zh），空字符串 = 不翻译（V1 路径）

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
    t_req_start = time.time()

    # ---- 1. 提取 offerId ----
    offer_id = extract_offer_id(body.url)
    if not offer_id or not offer_id.isdigit():
        raise ValidationError(message="无法从链接中提取有效的商品 ID", msg_code="OFFER_ID_NOT_FOUND")
    if len(offer_id) < 8:
        raise ValidationError(message="商品 ID 格式不正确", msg_code="OFFER_ID_INVALID")

    # ---- 2. 全局限流（风险 #14 L3） ----
    if not await rate_limiter.check():
        logger.warning(f"Global rate limit hit from IP={request.client.host if request.client else '?'}")
        raise AppError(
            message="系统繁忙，请稍后重试",
            code="GLOBAL_RATE_LIMIT",
            msg_code="GLOBAL_RATE_LIMIT",
            http_status=429,
            details={"retry_after": "60秒"},
        )

    # ---- 3. 用户配额检查（JWT 中间件已校验，user_id 一定存在）----
    user_id: int = getattr(request.state, "user_id", 0) or 0
    if not user_id:
        raise AppError(message="请先登录", msg_code="LOGIN_REQUIRED", http_status=401)

    _user_repo = UserRepository()
    user_quota = await _user_repo.get_quota_info(user_id)
    if not user_quota:
        raise AppError(message="用户不存在", msg_code="USER_NOT_FOUND", http_status=404)

    quota = user_quota["quota"]
    tier = str(user_quota.get("tier", "free"))
    last_reset_date = user_quota.get("last_reset_date")

    # 懒重置：补地板，不削顶
    daily_floor = Config.DAILY_PAID_QUOTA if tier == "paid" else Config.DAILY_FREE_QUOTA
    today = date.today()
    if last_reset_date is None or last_reset_date < today:
        quota = await _user_repo.lazy_reset_daily_quota(user_id, tier, daily_floor)

    if quota <= 0:
        raise InsufficientQuotaError(
            resource_type="今日分析次数",
            msg_code="QUOTA_EXHAUSTED",
            details={"daily_limit": daily_floor},
        )

    # ---- 4. 启动后台分析（扣减在 start() 内，请求合并后执行）----
    task_id = await analyze_service.start(offer_id=offer_id, user_id=user_id, raw_url=body.url, lang=body.lang)
    t_elapsed = time.time() - t_req_start
    logger.info(
        f"[请求] POST /api/analyze offer_id={offer_id} task_id={task_id} lang={body.lang or 'zh'} "
        f"启动Apify | 耗时={t_elapsed:.2f}s | user_id={user_id}"
    )

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
    if not re.match(r'^[a-f0-9-]{8,36}$', task_id):
        raise ValidationError(msg_code="TASK_NOT_FOUND", message="无效的任务ID")
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

    # 任务完成 → 日志记录 display JSON 大小
    if task.get("status") == "done":
        result: dict[str, Any] = task.get("result", {}) or {}
        display: dict[str, Any] = result.get("display", {}) or {}
        display_size = len(str(display))
        created = task.get("created_at", 0)
        elapsed = time.time() - created if created else 0
        logger.info(
            f"[请求] GET /api/analyze/{task_id} status=done "
            f"displaySize={display_size}B 分析耗时={elapsed:.1f}s"
        )

    return {
        "code": 200,
        "msg_code": "OK",
        "data": task,
        "message": "ok",
    }


# ====================================================================
# GET /api/quota — 查询当前用户剩余配额
# ====================================================================

@router.get("/api/quota")
async def get_quota(request: Request) -> dict[str, Any]:
    """返回当前用户的配额信息，供插件显示。

    需 JWT 认证（/api/ 前缀自动拦截）。
    """
    user_id: int = getattr(request.state, "user_id", 0) or 0
    if not user_id:
        raise AppError(message="请先登录", msg_code="LOGIN_REQUIRED", http_status=401)

    _user_repo = UserRepository()
    user_quota = await _user_repo.get_quota_info(user_id)
    if not user_quota:
        raise AppError(message="用户不存在", msg_code="USER_NOT_FOUND", http_status=404)

    quota = user_quota["quota"]
    tier = str(user_quota.get("tier", "free"))
    last_reset_date = user_quota.get("last_reset_date")

    # 懒重置：补地板
    daily_floor = Config.DAILY_PAID_QUOTA if tier == "paid" else Config.DAILY_FREE_QUOTA
    today = date.today()
    if last_reset_date is None or last_reset_date < today:
        quota = await _user_repo.lazy_reset_daily_quota(user_id, tier, daily_floor)

    return {
        "code": 200,
        "msg_code": "OK",
        "data": {
            "remaining": quota,
            "daily_limit": daily_floor,
            "tier": tier,
            "history_max": Config.HISTORY_PAID_MAX if tier == "paid" else Config.HISTORY_FREE_MAX,
        },
        "message": "ok",
    }
