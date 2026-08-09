"""日志工具 — 文件轮转 + 控制台双输出，支持脱敏配置。"""

import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 默认日志目录：src/api/logs/（从 logger.py 的 __file__ 推导）
_DEFAULT_LOG_DIR = str(Path(__file__).resolve().parent.parent / "logs")

# ---- 脱敏 ----

def sanitize(text: str) -> str:
    """脱敏日志中的敏感信息：email → 前3位***@***，token → 只记长度。"""
    # email: abc@def.com → abc***@***
    text = re.sub(r'([a-zA-Z0-9._%+-]{1,3})[a-zA-Z0-9._%+-]*@([a-zA-Z0-9.-]+)',
                  r'\1***@***', text)
    # token 出现在 URL query 或日志中
    text = re.sub(r'token=([^&\s]+)',
                  lambda m: f'token=***({len(m.group(1))}chars)', text)
    return text


class SanitizingFormatter(logging.Formatter):
    """在格式化前对日志消息执行脱敏。"""
    def format(self, record: logging.LogRecord) -> str:
        record.msg = sanitize(str(record.msg))
        return super().format(record)


def get_logger(
    name: str,
    log_dir: str = "",
    level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """获取配置好的 logger 实例。

    Args:
        name: logger 名称，通常传 __name__
        log_dir: 日志目录（相对或绝对路径）
        level: 日志级别
        max_bytes: 单个日志文件上限
        backup_count: 保留的轮转文件数

    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # 避免重复添加 handler

    logger.setLevel(level)
    logger.propagate = False

    formatter = SanitizingFormatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台输出
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # 文件轮转：LOG_DIR 环境变量 > 代码传入 > 默认 src/api/logs/
    resolved_dir = log_dir or os.getenv("LOG_DIR", _DEFAULT_LOG_DIR)
    log_path = Path(resolved_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_path / f"{name.split('.')[-1] or 'app'}.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


