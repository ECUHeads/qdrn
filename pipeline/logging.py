"""
Structured JSON Logging Module.

Provides production-grade structured logging with JSON formatting for
machine-parseable observability. All components emit logs through this module.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """JSON-formatted log handler for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "component": getattr(record, "component", "unknown"),
            "event_type": getattr(record, "event_type", None),
        }
        if hasattr(record, "payload"):
            log_entry["payload"] = record.payload
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


class ComponentAdapter(logging.LoggerAdapter):
    """Logger adapter that injects component name into every log record."""

    def process(self, msg: str, kwargs: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        kwargs.setdefault("extra", {}).setdefault("component", self.extra.get("component", "unknown"))  # type: ignore[arg-type]
        return msg, kwargs


def setup_logging(level: str = "INFO", json_format: bool = True) -> None:
    """Configure root logger with JSON or standard formatting."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
    root.addHandler(handler)


def get_logger(
    name: str,
    level: Optional[str] = None,
    component: str | None = None,
) -> logging.Logger | ComponentAdapter:
    """Get a configured logger instance, optionally wrapped with component context."""
    logger = logging.getLogger(name)
    if level:
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if component:
        return ComponentAdapter(logger, {"component": component})
    return logger


