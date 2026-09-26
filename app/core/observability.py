"""Sentry + structlog. Вызывается из main при старте процесса."""

from __future__ import annotations

import logging

APP_VERSION = "0.1.0"


def init_sentry() -> bool:
    """Инициализировать Sentry, если задан SENTRY_DSN. Возвращает True если включён."""
    from app.core.config import get_settings

    dsn = get_settings().sentry_dsn
    if not dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        release=f"playmystation@{APP_VERSION}",
        traces_sample_rate=0.2,
        send_default_pii=False,
    )
    logging.getLogger("playmystation").info("Sentry enabled")
    return True


def configure_structlog() -> None:
    """Настроить structlog поверх stdlib.

    При LOG_FORMAT=json — структурированные JSON-логи (для прода и Loki);
    иначе stdlib остаётся как есть, structlog просто прокидывает в него.
    Существующие logging.getLogger-вызовы работают в обоих режимах.
    """
    import structlog

    from app.core.config import get_settings

    if get_settings().log_format == "json":
        processors: list = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
            structlog.dev.ConsoleRenderer(colors=False),
        ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
