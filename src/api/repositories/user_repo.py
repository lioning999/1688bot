"""users 表数据访问 — Google 登录用户的增改查。"""

from typing import Any

import aiomysql  # type: ignore[import-untyped]

from config import Config
from database import AsyncDatabaseConnection
from utils.logger import get_logger

logger = get_logger(__name__)


class UserRepository:
    """users 表 CRUD。事务由 service 层控制。"""

    async def get_by_google_id(self, google_id: str) -> dict[str, Any] | None:
        """按 google_id 查用户，无记录返回 None。"""
        conn = await AsyncDatabaseConnection.get_connection()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT id, google_id, email, name, avatar_url, tier, quota, last_reset_date, default_lang, created_at, last_login FROM users WHERE google_id=%s",
                    (google_id,),
                )
                return await cur.fetchone()
        finally:
            await AsyncDatabaseConnection.close_connection(conn)

    async def get_by_telegram_uid(self, telegram_uid: str) -> dict[str, Any] | None:
        """按 telegram_uid 查用户（bot 身份），无记录返回 None。"""
        conn = await AsyncDatabaseConnection.get_connection()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT id, google_id, telegram_uid, email, name, avatar_url, tier, quota, last_reset_date, default_lang, created_at, last_login FROM users WHERE telegram_uid=%s",
                    (telegram_uid,),
                )
                return await cur.fetchone()
        finally:
            await AsyncDatabaseConnection.close_connection(conn)

    async def create(self, google_id: str, email: str | None = None,
                     name: str | None = None, avatar_url: str | None = None,
                     default_lang: str | None = None) -> int:
        """创建新用户，返回自增 ID。quota = Config.SIGNUP_BONUS_QUOTA（注册赠送）。"""
        conn = await AsyncDatabaseConnection.get_connection()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "INSERT INTO users (google_id, email, name, avatar_url, quota, default_lang, last_reset_date) "
                    "VALUES (%s, %s, %s, %s, %s, %s, CURDATE())",
                    (google_id, email, name, avatar_url, Config.SIGNUP_BONUS_QUOTA, default_lang),
                )
                await conn.commit()
                return cur.lastrowid  # type: ignore[return-value]
        except Exception:
            await conn.rollback()
            raise
        finally:
            await AsyncDatabaseConnection.close_connection(conn)

    async def create_by_telegram(self, telegram_uid: str, default_lang: str | None = None) -> int:
        """创建 bot 用户（google_id 为空），返回自增 ID。quota = DAILY_FREE_QUOTA（免费每天3次）。"""
        conn = await AsyncDatabaseConnection.get_connection()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "INSERT INTO users (telegram_uid, google_id, quota, default_lang, last_reset_date) "
                    "VALUES (%s, NULL, %s, %s, CURDATE())",
                    (telegram_uid, Config.DAILY_FREE_QUOTA, default_lang),
                )
                await conn.commit()
                return cur.lastrowid  # type: ignore[return-value]
        except Exception:
            await conn.rollback()
            raise
        finally:
            await AsyncDatabaseConnection.close_connection(conn)

    async def update_last_login(self, google_id: str, name: str | None = None,
                                avatar_url: str | None = None) -> None:
        """更新 last_login，同时刷新 name 和 avatar（Google 账号可能更新）。"""
        conn = await AsyncDatabaseConnection.get_connection()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "UPDATE users SET last_login=NOW(), name=%s, avatar_url=%s WHERE google_id=%s",
                    (name, avatar_url, google_id),
                )
                await conn.commit()
        except Exception:
            await conn.rollback()
            raise
        finally:
            await AsyncDatabaseConnection.close_connection(conn)

    # ------------------------------------------------------------------
    # 配额操作（V2：按 tier 每日补地板，懒重置）
    # ------------------------------------------------------------------

    async def get_quota_info(self, user_id: int) -> dict[str, Any] | None:
        """读用户配额信息。返回 None 表示用户不存在。"""
        conn = await AsyncDatabaseConnection.get_connection()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT id, tier, quota, last_reset_date FROM users WHERE id=%s",
                    (user_id,),
                )
                return await cur.fetchone()
        finally:
            await AsyncDatabaseConnection.close_connection(conn)

    async def decrement_quota(self, user_id: int) -> bool:
        """原子扣减 1 次配额。返回 True = 扣减成功，False = quota 不足。"""
        conn = await AsyncDatabaseConnection.get_connection()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "UPDATE users SET quota = quota - 1 WHERE id=%s AND quota > 0",
                    (user_id,),
                )
                await conn.commit()
                return cur.rowcount > 0
        except Exception:
            await conn.rollback()
            raise
        finally:
            await AsyncDatabaseConnection.close_connection(conn)

    async def increment_quota(self, user_id: int) -> None:
        """退还 1 次配额（Apify 失败时调用）。"""
        conn = await AsyncDatabaseConnection.get_connection()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "UPDATE users SET quota = quota + 1 WHERE id=%s",
                    (user_id,),
                )
                await conn.commit()
        except Exception:
            await conn.rollback()
            raise
        finally:
            await AsyncDatabaseConnection.close_connection(conn)

    async def lazy_reset_daily_quota(self, user_id: int, tier: str, daily_floor: int) -> int:
        """懒重置每日配额（补地板，不削顶）。返回重置后的 quota 值。

        规则：
          - last_reset_date IS NULL → 首次检查，只打日期戳，不动 quota（保留注册赠送）
          - last_reset_date < 今天 AND quota < 地板 → 补到地板
          - last_reset_date < 今天 AND quota >= 地板 → 只更新日期，不动 quota
          - last_reset_date = 今天 → 不动
        """
        conn = await AsyncDatabaseConnection.get_connection()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # Step 1: 首次检查（last_reset_date IS NULL）→ 只打日期戳
                await cur.execute(
                    "UPDATE users SET last_reset_date = CURDATE() "
                    "WHERE id = %s AND last_reset_date IS NULL",
                    (user_id,),
                )
                # Step 2: 跨天 + quota < 地板 → 补到地板
                await cur.execute(
                    "UPDATE users SET quota = %s, last_reset_date = CURDATE() "
                    "WHERE id = %s AND last_reset_date < CURDATE() AND quota < %s",
                    (daily_floor, user_id, daily_floor),
                )
                # Step 3: 跨天 + quota >= 地板 → 只更新日期
                await cur.execute(
                    "UPDATE users SET last_reset_date = CURDATE() "
                    "WHERE id = %s AND last_reset_date < CURDATE() AND quota >= %s",
                    (user_id, daily_floor),
                )
                await conn.commit()
                await cur.execute("SELECT quota FROM users WHERE id=%s", (user_id,))
                row = await cur.fetchone()
                return row["quota"] if row else 0
        except Exception:
            await conn.rollback()
            raise
        finally:
            await AsyncDatabaseConnection.close_connection(conn)

    async def update_default_lang(self, user_id: int, lang: str) -> None:
        """更新用户默认语言。"""
        conn = await AsyncDatabaseConnection.get_connection()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "UPDATE users SET default_lang=%s WHERE id=%s",
                    (lang, user_id),
                )
                await conn.commit()
        except Exception:
            await conn.rollback()
            raise
        finally:
            await AsyncDatabaseConnection.close_connection(conn)

    # ------------------------------------------------------------------
    # Admin 管理（自用：用户列表 + 会员切换 + 加配额）
    # ------------------------------------------------------------------

    async def list_users(self) -> list[dict[str, Any]]:
        """全部用户列表（按注册时间倒序）。"""
        conn = await AsyncDatabaseConnection.get_connection()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT id, email, name, tier, quota, default_lang, created_at, last_login "
                    "FROM users ORDER BY created_at DESC"
                )
                rows = await cur.fetchall()
                return [dict(r) for r in rows]
        finally:
            await AsyncDatabaseConnection.close_connection(conn)

    async def toggle_tier(self, user_id: int) -> str:
        """切换会员等级（free↔paid）。返回切换后的 tier；用户不存在返回空串。"""
        conn = await AsyncDatabaseConnection.get_connection()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("SELECT tier FROM users WHERE id=%s", (user_id,))
                row = await cur.fetchone()
                if not row:
                    return ""
                new_tier = "free" if row["tier"] == "paid" else "paid"
                await cur.execute("UPDATE users SET tier=%s WHERE id=%s", (new_tier, user_id))
                await conn.commit()
                return new_tier
        except Exception:
            await conn.rollback()
            raise
        finally:
            await AsyncDatabaseConnection.close_connection(conn)

    async def add_quota(self, user_id: int, amount: int) -> int:
        """给用户加配额。返回加后的 quota；用户不存在返回 0。"""
        conn = await AsyncDatabaseConnection.get_connection()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("UPDATE users SET quota = quota + %s WHERE id=%s", (amount, user_id))
                await conn.commit()
                await cur.execute("SELECT quota FROM users WHERE id=%s", (user_id,))
                row = await cur.fetchone()
                return row["quota"] if row else 0
        except Exception:
            await conn.rollback()
            raise
        finally:
            await AsyncDatabaseConnection.close_connection(conn)
