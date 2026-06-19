"""日志系统，基于 loguru"""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from .config import get_config

_initialized = False


def setup_logging() -> None:
    """初始化全局日志配置"""
    global _initialized
    if _initialized:
        return

    config = get_config()
    log_level = config.get("logging.level", "INFO")
    log_file = config.get("logging.file")
    rotation = config.get("logging.rotation", "10 MB")
    retention = config.get("logging.retention", "30 days")
    console = config.get("logging.console", True)

    # 移除默认 handler
    logger.remove()

    # 控制台输出
    if console:
        logger.add(
            sys.stderr,
            level=log_level,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                "<level>{message}</level>"
            ),
            colorize=True,
        )

    # 文件输出
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_file,
            level=log_level,
            rotation=rotation,
            retention=retention,
            format=(
                "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
                "{name}:{function}:{line} - {message}"
            ),
            encoding="utf-8",
        )

    _initialized = True


def get_logger():
    """获取 logger 实例"""
    if not _initialized:
        setup_logging()
    return logger
