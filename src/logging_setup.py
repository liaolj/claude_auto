"""Logging configuration for AnyRouter automation."""
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from typing import Any, Dict

from zoneinfo import ZoneInfo

from .config import Config
from .utils import ensure_directories, get_timezone, now_tz


class JsonFormatter(logging.Formatter):
    """Format log records as JSON lines."""

    def __init__(self, tz: ZoneInfo | None = None) -> None:
        super().__init__()
        self._tz = tz

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        payload: Dict[str, Any] = {
            "ts": getattr(record, "ts", None) or now_tz(self._tz).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        for key in ("run_id", "step", "action", "selector", "result", "error_code", "retry", "duration_ms", "url"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(config: Config, run_id: str) -> logging.Logger:
    """Configure a JSON rotating log handler and return the module logger."""
    ensure_directories((config.logging.log_file.parent,))
    logger = logging.getLogger("anyrouter")
    logger.setLevel(logging.INFO)
    tz = get_timezone(config.timezone)

    handler = RotatingFileHandler(
        filename=config.logging.log_file,
        maxBytes=config.run.log_max_bytes,
        backupCount=config.run.log_backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(JsonFormatter(tz))
    logger.addHandler(handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(JsonFormatter(tz))
    logger.addHandler(stream_handler)

    logger = logging.LoggerAdapter(logger, extra={"run_id": run_id})
    return logger
