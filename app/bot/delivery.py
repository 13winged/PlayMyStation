"""Доставка аудио в чат: кеш file_id → докачка → отправка → канал.

Общая для /now и скачивания по ссылке. Best-effort: тихо, без спама в чат.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import SessionFactory
from app.core.redis import get_cached_audio_file_id, set_cached_audio_file_id
from app.db import repositories as repo
from app.db.models import User
from app.services.audio import audio_cache_key, safe_filename
from app.services.base import BaseMusicService, TrackDTO
from app.services.factory import build_service
from app.services.youtube import YouTubeAuthExpired

log = logging.getLogger("playmystation.delivery")

# Докачка идёт вне bulkhead-таймаута /now: YT-трек может качаться минуту+.
DOWNLOAD_TIMEOUT = 120.0

# Параллельных докачек всего: 45МБ-треки в памяти, бережём RAM/CPU.
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(3)


def anonymous_service(provider: str, youtube_auth: str | None = None) -> BaseMusicService | None:
    """Сервис для треков по ссылке без привязки провайдера.

    Spotify: download_track не трогает токен (метаданные + preview/матчинг).
    YouTube: с auth юзера (куки) или анонимно.
    """
    if provider == "spotify":
        from app.services.spotify import SpotifyService

        return SpotifyService(token="")
    if provider == "youtube":
        from app.services.youtube import YouTubeMusicService

        return YouTubeMusicService(youtube_auth or "{}")
    return None


async def resolve_youtube_auth(session: AsyncSession, db_user: User) -> str | None:
    """Auth-JSON YouTube-привязки юзера (для матчинга/кук). None если нет."""
    integrations = await repo.list_integrations(session, db_user.id)
    yt = next((i for i in integrations if i.provider == "youtube"), None)
    return repo.decrypted_access(yt) if yt is not None else None


async def download_for_track(
    session: AsyncSession, db_user: User, track: TrackDTO
) -> tuple[bytes, str] | None:
    """Скачать аудио трека: привязанный сервис, иначе анонимный. None если никак."""
    integrations = await repo.list_integrations(session, db_user.id)
    integ = next((i for i in integrations if i.provider == track.provider), None)
    youtube_auth = None
    if track.provider in ("spotify", "lastfm"):
        yt = next((i for i in integrations if i.provider == "youtube"), None)
        youtube_auth = repo.decrypted_access(yt) if yt is not None else None
    svc: BaseMusicService | None = None
    if integ is not None:
        svc = await build_service(integ, session)
    if svc is None:
        svc = anonymous_service(track.provider, youtube_auth)
    if svc is None:
        return None
    try:
        async with DOWNLOAD_SEMAPHORE:
            return await asyncio.wait_for(
                svc.download_track(track, youtube_auth=youtube_auth),
                timeout=DOWNLOAD_TIMEOUT,
            )
    except YouTubeAuthExpired:
        raise
    except (TimeoutError, Exception):  # noqa: BLE001 — докачка не обязана успевать
        log.info("download failed/timeout: %s '%s'", track.provider, track.title)
        return None


async def store_to_cache_channel(
    bot: Bot, cache_key: str, data: bytes, filename: str, track: TrackDTO
) -> None:
    """Отправить трек в приватный канал и запомнить file_id. Best-effort."""
    channel_id = get_settings().audio_cache_channel_id
    if not channel_id:
        return
    try:
        sent = await bot.send_audio(
            chat_id=channel_id,
            audio=BufferedInputFile(data, filename=filename),
            title=track.title,
            performer=track.artist,
        )
        if sent.audio is not None:
            await set_cached_audio_file_id(cache_key, sent.audio.file_id)
    except Exception:
        log.info("audio cache channel store failed", exc_info=True)


async def fetch_and_send(
    message: Message, db_user: User, track: TrackDTO, notify_auth_expired: bool = False
) -> bool:
    """Полный цикл отдачи аудио. True если делать больше нечего
    (аудио ушло ИЛИ юзер уже уведомлён)."""
    from app.bot.i18n import lang_of, t
    cache_key = audio_cache_key(track)
    if cache_key is None:
        return False
    file_id = await get_cached_audio_file_id(cache_key)
    if file_id:
        try:
            await message.answer_audio(audio=file_id, title=track.title, performer=track.artist)
            return True
        except TelegramAPIError:
            log.info("stale audio file_id, re-downloading '%s'", track.title)
    try:
        async with SessionFactory() as session:
            result = await download_for_track(session, db_user, track)
            if result is None:
                return False
            data, ext = result
            filename = safe_filename(track.artist, track.title, ext=ext)
            await message.answer_audio(
                BufferedInputFile(data, filename=filename),
                title=track.title,
                performer=track.artist,
            )
            await store_to_cache_channel(message.bot, cache_key, data, filename, track)
            return True
    except YouTubeAuthExpired:
        if notify_auth_expired:
            await message.answer(t(lang_of(db_user), "link_cookies_expired"))
        else:
            log.info("youtube cookies expired for '%s'", track.title)
        return True
    except Exception:
        log.exception("delivery crashed")
        return False
