"""FastAPI 应用入口 — 创建 app、中间件、路由注册。"""

from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from config import Config
from database import AsyncDatabaseConnection
from middleware import JWTAuthMiddleware
from routes.auth import auth_router, callback_router
from routes.analyze import router as analyze_router
from routes.history import router as history_router
from routes.proxy import router as proxy_router
from utils.exceptions import AppError
from utils.logger import get_logger

logger = get_logger(__name__)

# ---- Sentry 错误监控（必须在 app 创建之前初始化） ----
import sentry_sdk

sentry_sdk.init(
    dsn=Config.SENTRY_DSN if Config.SENTRY_DSN else None,
    send_default_pii=True,
    enable_logs=True,
    traces_sample_rate=0.1,
)


# ---- 生命周期 ----
@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动：验证配置 → 初始化数据库连接池。关闭：释放连接池。"""
    Config.validate()
    await AsyncDatabaseConnection.get_pool()
    yield
    await AsyncDatabaseConnection.close_pool()


app = FastAPI(
    title=Config.APP_NAME,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if Config.TEST_MODE else None,
    redoc_url=None,
)

# ---- CORS ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: 生产环境限定域名
    allow_credentials=False,  # Bug #18: allow_origins=["*"] 不能与 allow_credentials=True 并存
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- GZip（Bug #24：压缩静态文件，海外用户加载更快） ----
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ---- JWT 认证中间件 ----
app.add_middleware(JWTAuthMiddleware)

# ---- 全局异常处理器 ----
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.http_status,
        content=exc.to_dict(),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"code": 422, "data": None, "message": "输入验证失败"},
    )


@app.exception_handler(Exception)
async def catch_all_handler(request: Request, exc: Exception):
    """兜底：非预期异常统一返回 {code, data, message}，不泄漏内部细节。"""
    logger.exception(f"Unhandled exception: {request.url.path}")
    return JSONResponse(
        status_code=500,
        content={"code": 500, "data": None, "message": "服务器内部错误，请稍后重试"},
    )


# ===== 健康检查 =====
@app.get("/health")
async def health_check():
    """Bug #22：验 DB 连通性，方便运维监控。"""
    db_ok = True
    try:
        conn = await AsyncDatabaseConnection.get_connection()
        await AsyncDatabaseConnection.close_connection(conn)
    except Exception as e:
        db_ok = False
        logger.warning(f"Health check DB failed: {e}")
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
    }


# ---- 公开配置（前端启动时取一次） ----
@app.get("/api/config")
async def public_config():
    """返回前端需要的公开配置（不含敏感信息）。汇率从此一处配置。"""
    return {
        "code": 200,
        "data": {
            "cnyUsdRate": Config.CNY_USD_RATE,
            "fxRates": {
                "VND": Config.FX_VND,
                "THB": Config.FX_THB,
                "IDR": Config.FX_IDR,
                "MYR": Config.FX_MYR,
                "PHP": Config.FX_PHP,
            },
        },
        "message": "ok",
    }


# ---- API 路由（必须在 StaticFiles mount 之前注册） ----
app.include_router(auth_router)
app.include_router(callback_router)
app.include_router(analyze_router)
app.include_router(history_router)
app.include_router(proxy_router)


# ---- 前端静态文件（最后注册，作为 fallback） ----
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


# ===== 入口 =====
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=Config.PORT,
        reload=Config.DEBUG,
    )
