"""历史记录 API — 登录用户查看/删除过往分析记录（只读 DB，不调 Apify）。"""

import re
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, field_validator

from services.analyze_svc import analyze_service
from utils.exceptions import AppError, ValidationError
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["history"])


@router.get("/api/history")
async def list_history(request: Request, lang: str = "") -> dict[str, Any]:
    """返回当前用户最近 20 条分析记录。

    需 JWT 认证（/api/ 前缀自动拦截）。
    只读 analysis 表，不调任何外部服务。
    lang → 列表标题/结论档位优先取该语言 display（命中优先，缺则存储第一个）。
    """
    user_id: int = getattr(request.state, "user_id", 0) or 0
    if not user_id:
        raise AppError(message="请先登录", code="LOGIN_REQUIRED", msg_code="LOGIN_REQUIRED",
                       http_status=401)

    items = await analyze_service.get_history(user_id, lang=lang)
    logger.info(f"[History] 列表查询 user_id={user_id} 记录数={len(items)}")
    return {"code": 200, "msg_code": "OK", "data": {"items": items}, "message": "ok"}


@router.delete("/api/history/{analysis_id}")
async def delete_history(analysis_id: int, request: Request) -> dict[str, Any]:
    """删除一条分析记录。校验归属后才删除。需 JWT 认证（/api/ 前缀自动拦截）。"""
    if analysis_id <= 0:
        raise ValidationError(msg_code="HISTORY_NOT_FOUND", message="无效的记录ID")
    user_id: int = getattr(request.state, "user_id", 0) or 0
    if not user_id:
        raise AppError(message="请先登录", code="LOGIN_REQUIRED", msg_code="LOGIN_REQUIRED",
                       http_status=401)

    deleted = await analyze_service.delete_record(analysis_id, user_id)
    if not deleted:
        logger.warning(f"[History] 删除失败-无权或不存在 id={analysis_id} user_id={user_id}")
        raise AppError(message="记录不存在或无权操作", code="HISTORY_NOT_FOUND",
                       msg_code="HISTORY_NOT_FOUND", http_status=404)

    logger.info(f"[History] 删除成功 id={analysis_id} user_id={user_id}")
    return {"code": 200, "msg_code": "DELETE_OK", "data": None, "message": "已删除"}


class FavoriteRequest(BaseModel):
    analysis_id: int

    @field_validator("analysis_id")
    @classmethod
    def must_be_valid(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("无效的记录ID")
        return v


@router.post("/api/history/favorite")
async def toggle_favorite(body: FavoriteRequest, request: Request) -> dict[str, Any]:
    """切换历史记录的收藏状态。收藏后不参与 FIFO 自动清理。

    需 JWT 认证。
    """
    user_id: int = getattr(request.state, "user_id", 0) or 0
    if not user_id:
        raise AppError(message="请先登录", code="LOGIN_REQUIRED", msg_code="LOGIN_REQUIRED",
                       http_status=401)

    result = await analyze_service.toggle_favorite(body.analysis_id, user_id)
    if result is None:
        raise AppError(message="记录不存在或无权操作", code="HISTORY_NOT_FOUND",
                       msg_code="HISTORY_NOT_FOUND", http_status=404)

    logger.info(f"[History] 收藏切换 id={body.analysis_id} user_id={user_id} → {'★' if result else '☆'}")
    return {"code": 200, "msg_code": "OK", "data": {"favorited": result}, "message": "ok"}


@router.get("/api/report/{offer_id}")
async def get_report(offer_id: str, request: Request, lang: str = "") -> dict[str, Any]:
    """从 DB 加载已保存的分析报告。display_i18n 懒加载（请求某语言时才翻译）。

    需 JWT 认证。
    """
    if not re.match(r'^\d+$', offer_id):
        raise ValidationError(msg_code="OFFER_ID_INVALID", message="无效的商品ID")
    user_id: int = getattr(request.state, "user_id", 0) or 0
    if not user_id:
        raise AppError(message="请先登录", code="LOGIN_REQUIRED", msg_code="LOGIN_REQUIRED",
                       http_status=401)

    result = await analyze_service.get_saved_report(offer_id, user_id, lang)
    if result is None:
        logger.warning(f"[History] 报告未找到 offer_id={offer_id} user_id={user_id} lang={lang}")
        raise AppError(message="报告未找到", code="REPORT_NOT_FOUND", msg_code="REPORT_NOT_FOUND",
                       http_status=404)

    logger.info(f"[History] 报告详情 offer_id={offer_id} user_id={user_id} lang={lang or 'zh'}")
    return {"code": 200, "msg_code": "OK", "data": {"status": "done", "result": result}, "message": "ok"}
