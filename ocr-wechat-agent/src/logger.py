"""日志初始化模块：JSON 文件日志 + 人类可读控制台日志"""

import logging
import sys
from logging.handlers import RotatingFileHandler

from pythonjsonlogger.json import JsonFormatter

from config import LoggerConfig

LOGGER_NAME = "ocr-wechat-agent"


def init_logger(cfg: LoggerConfig) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(cfg.level.upper())

    if logger.handlers:
        return logger

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

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    console_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)-5s] %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(console_handler)

    return logger
