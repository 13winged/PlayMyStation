"""Фабрика стратегий: собирает нужный сервис по provider + Integration."""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repositories as repo
from app.db.models import Integration
from app.services.base import BaseMusicService, TrackDTO
from app.services.soundcloud import SoundCloudService
from app.services.spotify import SpotifyService
from app.services.yandex import YandexMusicService


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

    if integration.provider == "soundcloud":
        token = repo.decrypted_access(integration)
        if not token:
            return None
        return SoundCloudService(token)

    return None


async def resolve_now_playing(
    integrations: list[Integration],
    session: AsyncSession,
    active_provider: str = "all",
) -> TrackDTO | None:
    """Логика /now: если active != all — опрашиваем один сервис,
    иначе опрашиваем все привязанные параллельно и возвращаем тот, где is_playing."""
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
        return await services[0].get_currently_playing()

    results = await asyncio.gather(
        *(s.get_currently_playing() for s in services), return_exceptions=True
    )
    tracks = [r for r in results if isinstance(r, TrackDTO)]
    if not tracks:
        return None
    # Приоритет: реально играющий трек; иначе первый не-None (last played)
    for t in tracks:
        if t.is_playing:
            return t
    return tracks[0]
