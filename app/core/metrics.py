"""Prometheus-метрики: бот, провайдеры, HTTP, circuit breakers.

Все метрики — в дефолтном REGISTRY, отдаются через GET /metrics.
Кардинальность лейблов ограничена: команды/колбэки нормализуются,
HTTP-пути берутся из шаблонов роутов, а не из сырых URL.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Histogram,
    generate_latest,
)
from prometheus_client.core import GaugeMetricFamily

# ----- Bot updates -----
bot_updates_total = Counter(
    "pms_bot_updates_total",
    "Обработанные Telegram-апдейты.",
    ["update_type", "command"],
)
bot_update_errors_total = Counter(
    "pms_bot_update_errors_total",
    "Апдейты, упавшие с исключением.",
    ["update_type", "command"],
)
bot_update_duration_seconds = Histogram(
    "pms_bot_update_duration_seconds",
    "Время обработки апдейта.",
    ["update_type", "command"],
)

# ----- Providers (/now) -----
provider_now_playing_total = Counter(
    "pms_provider_now_playing_total",
    "Опросы провайдеров (ok = трек найден).",
    ["provider", "result"],
)
provider_now_playing_duration_seconds = Histogram(
    "pms_provider_now_playing_duration_seconds",
    "Время опроса провайдера (включая bulkhead-таймаут).",
    ["provider"],
)
now_playing_cache_total = Counter(
    "pms_now_playing_cache_total",
    "Попадания/промахи Redis-кэша /now.",
    ["result"],
)

# ----- Audit -----
audit_total = Counter(
    "pms_audit_total",
    "События подключения/отключения провайдеров.",
    ["action", "provider"],
)

# ----- HTTP (FastAPI) -----
http_requests_total = Counter(
    "pms_http_requests_total",
    "HTTP-запросы к веб-серверу.",
    ["method", "path", "status"],
)
http_request_duration_seconds = Histogram(
    "pms_http_request_duration_seconds",
    "Время обработки HTTP-запроса.",
    ["method", "path"],
)


class CircuitBreakerCollector:
    """Состояния circuit breakers как gauge (1 = open)."""

    def __init__(self, reader: Callable[[], list[tuple[str, bool]]]) -> None:
        self._reader = reader

    def collect(self):  # type: ignore[no-untyped-def]
        gauge = GaugeMetricFamily(
            "pms_circuit_breaker_open",
            "Circuit breaker разомкнут (сервис не дёргаем).",
            labels=["provider"],
        )
        for provider, is_open in self._reader():
            gauge.add_metric([provider], 1 if is_open else 0)
        yield gauge


def _read_circuits() -> list[tuple[str, bool]]:
    # Локальный импорт — избегаем цикла (retry не зависит от metrics).
    from app.core.retry import (
        CROSSLINK_CIRCUIT,
        LASTFM_CIRCUIT,
        SPOTIFY_CIRCUIT,
        YANDEX_CIRCUIT,
        YOUTUBE_CIRCUIT,
    )

    return [
        ("spotify", SPOTIFY_CIRCUIT.is_open),
        ("yandex", YANDEX_CIRCUIT.is_open),
        ("youtube", YOUTUBE_CIRCUIT.is_open),
        ("lastfm", LASTFM_CIRCUIT.is_open),
        ("crosslink", CROSSLINK_CIRCUIT.is_open),
    ]


try:
    REGISTRY.register(CircuitBreakerCollector(_read_circuits))
except ValueError:
    pass  # коллектор уже зарегистрирован (переимпорт в тестах)


def render_metrics() -> tuple[bytes, str]:
    """Сгенерировать тело /metrics. Возвращает (bytes, content_type)."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def observe_provider(provider: str, duration_s: float, result: str) -> None:
    """Записать исход опроса провайдера. result ∈ {ok, none, error}."""
    provider_now_playing_total.labels(provider, result).inc()
    provider_now_playing_duration_seconds.labels(provider).observe(duration_s)


def count_cache(result: str) -> None:
    """Записать hit/miss кэша /now."""
    now_playing_cache_total.labels(result).inc()


def describe_update(event: Any) -> tuple[str, str]:
    """Нормализовать апдейт в (тип, команда) с ограниченной кардинальностью."""
    from aiogram.types import CallbackQuery, Message

    if isinstance(event, Message):
        text = (event.text or "").strip()
        if text.startswith("/"):
            command = text.split()[0].split("@")[0].lstrip("/")
            return "message", command or "unknown"
        return "message", "text"
    if isinstance(event, CallbackQuery):
        data = (event.data or "").strip()
        if data:
            return "callback_query", ":".join(data.split(":")[:2])
        return "callback_query", "unknown"
    return type(event).__name__, "unknown"


class Timer:
    """Простой замер длительности для histogram.observe."""

    def __init__(self) -> None:
        self._start = time.perf_counter()

    def elapsed(self) -> float:
        return time.perf_counter() - self._start
