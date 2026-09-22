"""Logging estructurado en JSON con request_id (basado en structlog)."""

import logging
import sys

import structlog
from structlog.stdlib import BoundLogger
from structlog.stdlib import get_logger as structlog_get_logger

from app.core.config import settings


def setup_logging() -> None:
    """Configura el logging estructurado en JSON."""
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> BoundLogger:
    """Devuelve un logger estructurado para el módulo indicado."""
    return structlog_get_logger(name)
