"""Async Redis client (кеш токенов / состояний / now_playing)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict

import redis.asyncio as redis

from app.core.config import get_settings
from app.services.base import TrackDTO

_redis: redis.Redis | None = None
log = logging.getLogger("playmystation.redis")

# TTL для кэша now_playing (15-30 сек защита от спама /now)
NOW_PLAYING_TTL = 20


async def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        settings = get_settings()
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


# ----- now_playing cache -----

def _now_playing_key(telegram_id: int) -> str:
    return f"now_playing:{telegram_id}"


async def get_cached_now_playing(telegram_id: int) -> TrackDTO | None:
    """Получить закэшированный трек, если есть."""
    r = await get_redis()
    data = await r.get(_now_playing_key(telegram_id))
    if data is None:
        return None
    try:
        return TrackDTO(**json.loads(data))
    except Exception:  # noqa: BLE001 — битый кэш = игнор
        return None


async def set_cached_now_playing(telegram_id: int, track: TrackDTO) -> None:
    """Закэшировать трек на NOW_PLAYING_TTL секунд."""
    r = await get_redis()
    try:
        # NOTE: TrackDTO — slots-датакласс, у него нет __dict__, поэтому asdict().
        await r.setex(
            _now_playing_key(telegram_id),
            NOW_PLAYING_TTL,
            json.dumps(asdict(track), default=str),
        )
    except Exception:  # noqa: BLE001 — кэш best-effort
        log.debug("Failed to cache now_playing for %s", telegram_id)


async def invalidate_now_playing_cache(telegram_id: int) -> None:
    """Инвалидировать кэш (например, после ручного переключения трека)."""
    r = await get_redis()
    await r.delete(_now_playing_key(telegram_id))
