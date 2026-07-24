"""MySQL 异步连接池 — 仅连接池生命周期，DDL 见 db/schema.sql。"""

import asyncio
from typing import Any

import aiomysql  # type: ignore[import-untyped]
from config import Config
from utils.logger import get_logger

logger = get_logger(__name__)


class AsyncDatabaseConnection:
    """异步数据库连接池（FastAPI 使用）。

    生命周期：
        startup  → get_pool()
        request  → get_connection() → use → close_connection()
        shutdown → close_pool()
    """

    _pool = None
    _pool_lock: asyncio.Lock = asyncio.Lock()

    @staticmethod
    async def get_pool() -> Any:
        if AsyncDatabaseConnection._pool is None:
            async with AsyncDatabaseConnection._pool_lock:
                if AsyncDatabaseConnection._pool is None:
                    try:
                        AsyncDatabaseConnection._pool = await aiomysql.create_pool(  # type: ignore[assignment]
                            host=Config.DB_HOST,
                            port=Config.DB_PORT,
                            user=Config.DB_USER,
                            password=Config.DB_PASSWORD,
                            db=Config.DB_NAME,
                            charset='utf8mb4',
                            minsize=Config.DB_POOL_MIN,
                            maxsize=Config.DB_POOL_MAX,
                            autocommit=False,
                        )
                        logger.info(
                            f"DATABASE_POOL_CREATED host={Config.DB_HOST} "
                            f"port={Config.DB_PORT} db={Config.DB_NAME}"
                        )
                    except Exception as e:
                        logger.error(f"DATABASE_POOL_CREATE_ERROR error={str(e)}")
                        raise
        return AsyncDatabaseConnection._pool  # type: ignore[return-value]

    @staticmethod
    async def get_connection() -> Any:
        pool = await AsyncDatabaseConnection.get_pool()
        conn = await pool.acquire()  # type: ignore[union-attr]
        # 清理残留事务：autocommit=False 下，连接可能携带前一次使用的未提交事务。
        # 如 Repository 层只读查询后未显式 commit/rollback，下一个拿到同连接的使用者
        # 会被卷入旧快照（REPEATABLE READ），INSERT → COMMIT → 查不到。
        try:
            await conn.rollback()
        except Exception:
            pass
        # 连接健康检查：AI 调用期间连接可能空闲 30-120s，
        # MySQL 可能关闭空闲连接，aiomysql 不会自动检测。
        try:
            await conn.ping(reconnect=True)
        except Exception:
            logger.warning("DATABASE_CONNECTION_STALE — 丢弃脏连接，重新获取")
            try:
                pool.release(conn)  # type: ignore[union-attr]
            except Exception:
                pass
            conn = await pool.acquire()  # type: ignore[union-attr]
            await conn.ping(reconnect=True)
        logger.debug("DATABASE_CONNECTION_ACQUIRED")
        return conn

    @staticmethod
    async def close_connection(conn: Any) -> None:
        if AsyncDatabaseConnection._pool and conn:
            try:
                AsyncDatabaseConnection._pool.release(conn)  # type: ignore[union-attr]
                logger.debug("DATABASE_CONNECTION_RELEASED")
            except Exception as e:
                logger.warning(f"DATABASE_CONNECTION_RELEASE_ERROR error={str(e)}")

    @staticmethod
    async def close_pool() -> None:
        if AsyncDatabaseConnection._pool:
            try:
                AsyncDatabaseConnection._pool.close()  # type: ignore[union-attr]
                await AsyncDatabaseConnection._pool.wait_closed()  # type: ignore[union-attr]
                AsyncDatabaseConnection._pool = None
                logger.info("DATABASE_POOL_CLOSED")
            except Exception as e:
                logger.error(f"DATABASE_POOL_CLOSE_ERROR error={str(e)}")
                raise
