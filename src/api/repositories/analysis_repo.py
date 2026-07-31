"""analysis 表数据访问 — 分析记录 CRUD。

覆盖风险清单：
  #12  查询历史存储 → 方案 B（存元数据），存 analysis 表
  V1.2  specs/skus/price_tiers 子表已废弃，数据统一存 result_json 列
"""

from typing import Any

import json
import aiomysql  # type: ignore[import-untyped]

from database import AsyncDatabaseConnection
from utils.logger import get_logger

logger = get_logger(__name__)


# ---- INSERT 列名（create / upsert 共用） ----
# V1.3：列字段只保留历史列表展示所需 + 系统字段。完整数据在 result_json + display_i18n。
_INSERT_COLS = (
    "user_id, offer_id, status, title, image_url, "
    "price_min, price_max, apify_task_id, result_json, display_i18n"
)
_INSERT_VALS = "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"


class AnalysisRepository:
    """analysis 表 CRUD。事务由 service 层控制。"""

    async def upsert(self, data: dict[str, Any]) -> int:
        """INSERT 或 UPDATE 分析记录（ON DUPLICATE KEY UPDATE）。"""
        conn = await AsyncDatabaseConnection.get_connection()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # 主表：INSERT ... ON DUPLICATE KEY UPDATE
                await cur.execute(
                    f"""INSERT INTO analysis ({_INSERT_COLS}) VALUES {_INSERT_VALS}
                       ON DUPLICATE KEY UPDATE
                        status=VALUES(status), title=VALUES(title), image_url=VALUES(image_url),
                        price_min=VALUES(price_min), price_max=VALUES(price_max),
                        result_json=VALUES(result_json), display_i18n=VALUES(display_i18n),
                        updated_at=NOW()""",
                    (
                        data["user_id"], data["offer_id"], data.get("status", "done"),
                        data.get("title"), data.get("image_url"),
                        data.get("price_min"), data.get("price_max"),
                        data.get("apify_task_id"),
                        data.get("result_json"),
                        data.get("display_i18n"),
                    ),
                )
                analysis_id = cur.lastrowid

                await conn.commit()
                return analysis_id  # type: ignore[return-value]
        except Exception:
            await conn.rollback()
            raise
        finally:
            await AsyncDatabaseConnection.close_connection(conn)

    async def count_by_user(self, user_id: int) -> int:
        """统计某用户的分析记录总数（仅 done 状态）。"""
        conn = await AsyncDatabaseConnection.get_connection()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT COUNT(*) AS cnt FROM analysis WHERE user_id=%s AND status='done'",
                    (user_id,),
                )
                row = await cur.fetchone()
                return row["cnt"] if row else 0  # type: ignore[return-value]
        finally:
            await AsyncDatabaseConnection.close_connection(conn)

    async def delete(self, analysis_id: int, user_id: int) -> bool:
        """删除一条分析记录。校验 user_id 归属，删除成功返回 True。"""
        conn = await AsyncDatabaseConnection.get_connection()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "DELETE FROM analysis WHERE id=%s AND user_id=%s",
                    (analysis_id, user_id),
                )
                await conn.commit()
                return cur.rowcount > 0
        except Exception:
            await conn.rollback()
            raise
        finally:
            await AsyncDatabaseConnection.close_connection(conn)

    async def get_by_offer_id(self, offer_id: str, user_id: int) -> dict[str, Any] | None:
        """从 DB 加载已保存的分析报告（Bug #1：历史→report 查 DB 不调 Apify）。

        读 result_json（完整），异常时回退到列字段拼凑最小结构。
        """
        conn = await AsyncDatabaseConnection.get_connection()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """SELECT offer_id, title, image_url, price_min, price_max,
                              result_json
                       FROM analysis
                       WHERE offer_id=%s AND user_id=%s AND status='done'
                       LIMIT 1""",
                    (offer_id, user_id),
                )
                row = await cur.fetchone()
                if row is None:
                    return None
                if row.get("result_json"):
                    try:
                        return json.loads(row["result_json"])
                    except (json.JSONDecodeError, TypeError):
                        pass  # JSON 损坏，回退到列字段
                # fallback：从列字段拼出最小可用结构
                return {
                    "title": row.get("title"),
                    "image": row.get("image_url"),
                    "offerId": row.get("offer_id"),
                    "priceCNY": {
                        "low": float(row["price_min"]) if row.get("price_min") else 0,
                        "high": float(row["price_max"]) if row.get("price_max") else 0,
                    },
                }
        finally:
            await AsyncDatabaseConnection.close_connection(conn)

    async def get_display_i18n(self, offer_id: str, user_id: int) -> str | None:
        """读 display_i18n 列（原始 JSON 字符串）。不存在返回 None。"""
        conn = await AsyncDatabaseConnection.get_connection()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT display_i18n FROM analysis WHERE offer_id=%s AND user_id=%s AND status='done' LIMIT 1",
                    (offer_id, user_id),
                )
                row = await cur.fetchone()
                if row and row.get("display_i18n"):
                    return row["display_i18n"]  # type: ignore[return-value]
                return None
        finally:
            await AsyncDatabaseConnection.close_connection(conn)

    async def update_display_i18n(self, offer_id: str, user_id: int, display_i18n_json: str) -> bool:
        """更新 display_i18n 列。返回 True 表示更新成功。"""
        conn = await AsyncDatabaseConnection.get_connection()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "UPDATE analysis SET display_i18n=%s WHERE offer_id=%s AND user_id=%s",
                    (display_i18n_json, offer_id, user_id),
                )
                await conn.commit()
                return cur.rowcount > 0
        except Exception:
            await conn.rollback()
            raise
        finally:
            await AsyncDatabaseConnection.close_connection(conn)

    async def get_history(self, user_id: int, limit: int = 20) -> list[dict[str, Any]]:
        """查用户最近的分析记录。"""
        conn = await AsyncDatabaseConnection.get_connection()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """SELECT id, offer_id, title, image_url, price_min, price_max,
                              created_at, display_i18n
                       FROM analysis
                       WHERE user_id=%s AND status='done'
                       ORDER BY created_at DESC LIMIT %s""",
                    (user_id, limit),
                )
                return await cur.fetchall()  # type: ignore[return-value]
        finally:
            await AsyncDatabaseConnection.close_connection(conn)
