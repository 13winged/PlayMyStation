"""Скачивание по ссылке из чата: трек Spotify/Яндекс/YouTube → аудио рядом.

Детект по домену, резолв метаданных, дальше общий fetch_and_send
(кеш file_id → докачка → канал). Одна активная закачка на юзера (лок).
Альбомы/плейлисты — вне скоупа: только одиночные треки.
"""

from __future__ import annotations

import asyncio
import logging
import re

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.delivery import fetch_and_send
from app.bot.formatters import track_card
from app.bot.i18n import lang_of, t
from app.bot.keyboards import track_kb
from app.core.redis import acquire_lock, release_lock
from app.db import repositories as repo
from app.db.models import User
from app.services.base import TrackDTO

router = Router()

log = logging.getLogger("playmystation.link")

SPOTIFY_TRACK_RE = re.compile(
    r"open\.spotify\.com/(?:intl-[a-z-]+/)?track/([A-Za-z0-9]{10,})"
)
YANDEX_TRACK_RE = re.compile(r"music\.yandex\.[a-z]+/album/(\d+)/track/(\d+)")
YOUTUBE_VIDEO_RE = re.compile(
    r"(?:youtube\.com/watch\?[^ ]*v=|youtu\.be/|music\.youtube\.com/watch\?[^ ]*v=)"
    r"([A-Za-z0-9_-]{6,})"
)


def parse_track_link(text: str) -> tuple[str, str] | None:
    """Найти ссылку на одиночный трек. Возвращает (provider, id) или None.

    Для Яндекса id вида 'track_id:album_id' (как playable_id).
    """
    m = SPOTIFY_TRACK_RE.search(text)
    if m:
        return ("spotify", m.group(1))
    m = YANDEX_TRACK_RE.search(text)
    if m:
        return ("yandex", f"{m.group(2)}:{m.group(1)}")
    m = YOUTUBE_VIDEO_RE.search(text)
    if m:
        return ("youtube", m.group(1))
    return None


async def _resolve_track(
    session: AsyncSession, db_user: User, provider: str, ref: str
) -> TrackDTO | None:
    """Метаданные трека по ссылке. None если не резолвится."""
    if provider == "spotify":
        from app.services.crosslink import spotify_track_meta

        return await spotify_track_meta(ref)
    if provider == "youtube":
        from app.services.youtube import youtube_video_meta

        return await youtube_video_meta(ref)
    if provider == "yandex":
        from app.services.yandex import YandexMusicService

        integrations = await repo.list_integrations(session, db_user.id)
        integ = next((i for i in integrations if i.provider == "yandex"), None)
        if integ is None:
            return None
        token = repo.decrypted_access(integ)
        if not token:
            return None
        return await YandexMusicService(token).fetch_track(ref)
    return None


@router.message(F.text, ~F.text.startswith("/"))
async def cmd_link(message: Message, session: AsyncSession, db_user: User) -> None:
    lang = lang_of(db_user)
    parsed = parse_track_link(message.text or "")
    if parsed is None:
        return
    provider, ref = parsed

    lock_key = f"linkdl:{db_user.telegram_id}"
    if not await acquire_lock(lock_key, 180):
        await message.answer(t(lang, "link_busy"))
        return
    scheduled = False
    try:
        if provider == "yandex":
            integrations = await repo.list_integrations(session, db_user.id)
            if not any(i.provider == "yandex" for i in integrations):
                await message.answer(t(lang, "link_need_yandex"))
                return
        track = await _resolve_track(session, db_user, provider, ref)
        if track is None:
            await message.answer(t(lang, "link_failed"))
            return
        kb = track_kb(
            has_preview=bool(track.preview_url),
            lang=lang,
            controls=(track.provider == "spotify"),
            playing=False,
        )
        if track.cover_url:
            await message.answer_photo(
                photo=track.cover_url, caption=track_card(track, lang), reply_markup=kb
            )
        else:
            await message.answer(track_card(track, lang), reply_markup=kb)
        # Докачка фоном, чтобы не держать хендлер минутами.
        # Лок переходит фоновой задаче — она же его и освободит.
        asyncio.create_task(_deliver_link(message, db_user, track, lock_key))
        scheduled = True
    except Exception:
        log.exception("link handler crashed")
    finally:
        if not scheduled:
            await release_lock(lock_key)


async def _deliver_link(message: Message, db_user: User, track: TrackDTO, lock_key: str) -> None:
    try:
        ok = await fetch_and_send(message, db_user, track)
        if not ok:
            await message.answer(t(lang_of(db_user), "link_failed"))
    finally:
        await release_lock(lock_key)
