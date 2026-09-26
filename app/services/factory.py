"""Фабрика стратегий: собирает нужный сервис по provider + Integration."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_cached_now_playing, set_cached_now_playing
from app.db import repositories as repo
from app.db.models import Integration
from app.services.base import BaseMusicService, TrackDTO
from app.services.lastfm import LastFmService
from app.services.spotify import SpotifyService
from app.services.yandex import YandexMusicService
from app.services.youtube import YouTubeMusicService

log = logging.getLogger("playmystation.factory")

# Bulkhead: максимум времени на один сервис. Медленный/зависший провайдер
# отваливается по таймауту и не задерживает ответ /now для остальных.
NOW_PLAYING_TIMEOUT = 10.0


async def _safe_get_playing(service: BaseMusicService) -> TrackDTO | None:
    """Опрос одного сервиса с таймаутом. Любая ошибка/таймаут → None."""
    try:
        track = await asyncio.wait_for(service.get_currently_playing(), timeout=NOW_PLAYING_TIMEOUT)
    except (TimeoutError, Exception):  # noqa: BLE001 — один сервис не должен ронять /now
        log.info("provider %s failed/timeout", service.provider)
        return None
    log.info(
        "provider %s -> %s",
        service.provider,
        f"'{track.title}'" if track else None,
    )
    return track


async def build_service(
    integration: Integration,
    session: AsyncSession,
) -> BaseMusicService | None:
    """Создаёт сервис по строке интеграции. Для Spotify прокидывает token-saver в БД."""
    if integration.provider == "spotify":
        access = repo.decrypted_access(integration)
        refresh = repo.decrypted_refresh(integration)
        if not access:
            return None

        async def _save(new_access: str, new_refresh: str | None, exp: dt.datetime | None) -> None:
            await repo.upsert_integration(
                session,
                user_id=integration.user_id,
                provider="spotify",
                access_token=new_access,
                refresh_token=new_refresh,
                expires_at=exp,
                service_user_id=integration.service_user_id,
            )
            await session.commit()

        saver: Callable[[str, str | None, dt.datetime | None], Awaitable[None]] = _save
        return SpotifyService(access, refresh, integration.expires_at, on_tokens_refreshed=saver)

    if integration.provider == "yandex":
        token = repo.decrypted_access(integration)
        if not token:
            return None
        return YandexMusicService(token)

    if integration.provider == "youtube":
        auth_json = repo.decrypted_access(integration)
        if not auth_json:
            return None
        return YouTubeMusicService(auth_json)

    if integration.provider == "lastfm":
        # У Last.fm нет токенов: username хранится в service_user_id.
        if not integration.service_user_id:
            return None
        return LastFmService(integration.service_user_id)

    return None


async def resolve_now_playing(
    integrations: list[Integration],
    session: AsyncSession,
    active_provider: str = "all",
    telegram_id: int | None = None,
) -> TrackDTO | None:
    """Логика /now: если active != all — опрашиваем один сервис,
    иначе опрашиваем все привязанные параллельно и возвращаем тот, где is_playing.

    Использует Redis-кэш (TTL ~20с) для защиты от спама /now.
    """
    # Проверяем кэш, если передан telegram_id
    if telegram_id is not None:
        cached = await get_cached_now_playing(telegram_id)
        if cached is not None:
            return cached

    if active_provider != "all":
        targets = [i for i in integrations if i.provider == active_provider]
    else:
        targets = integrations
    if not targets:
        return None

    services: list[BaseMusicService] = []
    for integ in targets:
        svc = await build_service(integ, session)
        if svc is not None:
            services.append(svc)
    if not services:
        return None
    if len(services) == 1:
        track = await _safe_get_playing(services[0])
    else:
        results = await asyncio.gather(
            *(_safe_get_playing(s) for s in services), return_exceptions=True
        )
        tracks = [r for r in results if isinstance(r, TrackDTO)]
        if not tracks:
            return None
        # Приоритет: реально играющий трек; иначе первый не-None (last played)
        track = None
        for t in tracks:
            if t.is_playing:
                track = t
                break
        if track is None:
            track = tracks[0]

    # Кэшируем результат
    if track is not None and telegram_id is not None:
        await set_cached_now_playing(telegram_id, track)

    return track
