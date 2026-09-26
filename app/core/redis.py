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

# TTL для кеша file_id скачанного аудио (повторная отдача без перекачивания)
AUDIO_CACHE_TTL = 30 * 24 * 3600


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


# ----- audio file_id cache (приватный канал как хранилище) -----


async def get_cached_audio_file_id(cache_key: str) -> str | None:
    """file_id ранее закачанного трека, если есть."""
    r = await get_redis()
    try:
        value = await r.get(f"audio_file:{cache_key}")
    except Exception:  # noqa: BLE001 — кэш best-effort
        return None
    return str(value) if value else None


async def set_cached_audio_file_id(cache_key: str, file_id: str) -> None:
    """Запомнить file_id трека на AUDIO_CACHE_TTL."""
    r = await get_redis()
    try:
        await r.setex(f"audio_file:{cache_key}", AUDIO_CACHE_TTL, file_id)
    except Exception:  # noqa: BLE001 — кэш best-effort
        log.debug("Failed to cache audio file_id for %s", cache_key)


# ----- song.link cache (мэппинги треков между платформами, стабильны) -----

SONGLINK_CACHE_TTL = 7 * 24 * 3600


async def get_cached_songlink(source_url: str) -> dict[str, str] | None:
    """Закешированные ссылки {platform: url} или None."""
    from app.services.songlink import songlink_cache_key

    r = await get_redis()
    try:
        data = await r.get(songlink_cache_key(source_url))
    except Exception:  # noqa: BLE001 — кэш best-effort
        return None
    if data is None:
        return None
    try:
        parsed = json.loads(data)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


async def set_cached_songlink(source_url: str, links: dict[str, str]) -> None:
    """Закешировать мэппинг на SONGLINK_CACHE_TTL."""
    from app.services.songlink import songlink_cache_key

    r = await get_redis()
    try:
        await r.setex(songlink_cache_key(source_url), SONGLINK_CACHE_TTL, json.dumps(links))
    except Exception:  # noqa: BLE001 — кэш best-effort
        log.debug("Failed to cache songlink for %s", source_url)


# ----- YouTube OAuth device-flow (ожидающие подтверждения) -----


def _yt_oauth_pending_key(telegram_id: int) -> str:
    return f"yt_oauth_pending:{telegram_id}"


async def set_pending_youtube_oauth(telegram_id: int, payload: dict, ttl_s: int) -> None:
    """Запомнить ожидающий device-flow (device_code, generation, ...)."""
    r = await get_redis()
    await r.setex(_yt_oauth_pending_key(telegram_id), ttl_s, json.dumps(payload))


async def get_pending_youtube_oauth(telegram_id: int) -> dict | None:
    """Прочитать ожидающий device-flow. None если нет/протух."""
    r = await get_redis()
    try:
        data = await r.get(_yt_oauth_pending_key(telegram_id))
    except Exception:  # noqa: BLE001 — best-effort
        return None
    if data is None:
        return None
    try:
        parsed = json.loads(data)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


async def delete_pending_youtube_oauth(telegram_id: int) -> None:
    r = await get_redis()
    await r.delete(_yt_oauth_pending_key(telegram_id))
