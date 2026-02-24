"""日志初始化模块：JSON 文件日志 + 人类可读控制台日志"""

import logging
import sys
from logging.handlers import RotatingFileHandler

from pythonjsonlogger.json import JsonFormatter

from config import LoggerConfig


def init_logger(cfg: LoggerConfig) -> logging.Logger:
    """初始化根 logger，同时配置文件输出（JSON）和控制台输出（人类可读）。"""
    logger = logging.getLogger("pywechat-agent")
    logger.setLevel(cfg.level.upper())

    # 防止重复添加 handler
    if logger.handlers:
        return logger

    # --- 文件日志：JSON 格式，RotatingFileHandler ---
    file_handler = RotatingFileHandler(
        filename=cfg.filename,
        maxBytes=cfg.max_bytes,
        backupCount=cfg.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level"},
        )
    )
    logger.addHandler(file_handler)

    # --- 控制台日志：人类可读格式 ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)-5s] %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(console_handler)

    return logger
