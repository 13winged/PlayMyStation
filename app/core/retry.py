"""Retry transport и circuit-breaker для httpx."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

log = logging.getLogger("playmystation.retry")


@dataclass
class CircuitBreaker:
    """Простой circuit breaker: после N ошибок переходит в OPEN на timeout секунд."""

    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    _failures: int = 0
    _state: str = "closed"  # closed | open | half-open
    _last_failure_time: float = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def is_open(self) -> bool:
        if self._state == "open":
            # Проверяем, не пора ли перейти в half-open
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = "half-open"
                return False
            return True
        return False

    async def record_success(self) -> None:
        async with self._lock:
            self._failures = 0
            self._state = "closed"

    async def record_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            self._last_failure_time = time.time()
            if self._failures >= self.failure_threshold:
                self._state = "open"
                log.warning("Circuit breaker OPENED after %d failures", self._failures)

    async def call(self, func: Callable, *args, **kwargs):
        """Выполнить func с защитой circuit breaker."""
        if await self._check_open():
            raise httpx.HTTPStatusError(
                "Circuit breaker is open", request=None, response=None
            )
        try:
            result = await func(*args, **kwargs)
            await self.record_success()
            return result
        except Exception:
            await self.record_failure()
            raise

    async def _check_open(self) -> bool:
        async with self._lock:
            if self._state == "open":
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = "half-open"
                    return False
                return True
            return False


def create_retry_transport(
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
    retry_on_status: tuple[int, ...] = (429, 500, 502, 503, 504),
) -> httpx.AsyncHTTPTransport:
    """Создать транспорт с ретраями для httpx.AsyncClient."""

    class RetryTransport(httpx.AsyncHTTPTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            delay = base_delay
            last_exc: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    response = await super().handle_async_request(request)

                    # Ретраим на rate limit / server errors
                    if response.status_code in retry_on_status:
                        # Respect Retry-After header если есть
                        retry_after = response.headers.get("Retry-After")
                        if retry_after:
                            try:
                                delay = min(float(retry_after), max_delay)
                            except ValueError:
                                pass

                        if attempt < max_retries:
                            log.warning(
                                "HTTP %d on %s, retry %d/%d in %.1fs",
                                response.status_code,
                                request.url,
                                attempt + 1,
                                max_retries,
                                delay,
                            )
                            await asyncio.sleep(delay)
                            delay = min(delay * 2, max_delay)  # exponential backoff
                            continue

                    return response

                except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError) as e:
                    last_exc = e
                    if attempt < max_retries:
                        log.warning(
                            "Network error on %s: %s, retry %d/%d in %.1fs",
                            request.url,
                            e,
                            attempt + 1,
                            max_retries,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, max_delay)
                        continue
                    raise

            # Если все ретраи исчерпаны
            if last_exc:
                raise last_exc
            # fallback (не должно случиться)
            return httpx.Response(500, request=request, content=b"Retries exhausted")

    return RetryTransport()


# Глобальные circuit breakers для каждого провайда
SPOTIFY_CIRCUIT = CircuitBreaker(failure_threshold=5, recovery_timeout=30)
YANDEX_CIRCUIT = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
SOUNDCLOUD_CIRCUIT = CircuitBreaker(failure_threshold=5, recovery_timeout=60)