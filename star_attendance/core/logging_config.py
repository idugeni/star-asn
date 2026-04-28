"""Structured logging configuration for Star ASN using structlog.

Provides JSON-structured logs for production (Loki/Grafana friendly)
and colored dev-friendly console output for development.
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_structlog(log_level: str = "INFO") -> None:
    """Configure structlog with both console and JSON processors.

    In production (LOG_FORMAT=json): outputs JSON-structured logs
    compatible with Loki/Grafana/ELK pipelines.

    In development (default): outputs colored, human-readable console logs.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure stdlib logging as the sink
    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stdout,
    )

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    # Choose renderer based on environment
    import os

    log_format = os.getenv("LOG_FORMAT", "console").lower()

    if log_format == "json":
        # Production: JSON output for Loki/Grafana
        renderer = structlog.processors.JSONRenderer()
    else:
        # Development: colored console
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Apply the formatter to the root handler
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processor_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger instance.

    Args:
        name: Optional logger name (typically __name__).

    Returns:
        A bound structlog logger.
    """
    return structlog.get_logger(name)
