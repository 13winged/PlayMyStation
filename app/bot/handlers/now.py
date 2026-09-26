"""Команда /now и /np: опрос активного сервиса или всех (режим ALL).

После карточки трека бот фоном докачивает аудио и присылает его
следующим сообщением (best-effort): Яндекс/YouTube — полный трек,
Spotify/Last.fm — YouTube-матчинг по метаданным (у Spotify фолбэк preview).
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatters import track_card
from app.bot.keyboards import now_empty_kb, track_kb
from app.core.config import get_settings
from app.core.db import SessionFactory
from app.core.redis import get_cached_audio_file_id, set_cached_audio_file_id
from app.db import repositories as repo
from app.db.models import User
from app.services.audio import audio_cache_key, fetch_audio_bytes, safe_filename
from app.services.base import TrackDTO
from app.services.factory import build_service, resolve_now_playing
from app.services.songlink import match_platform_links

router = Router()

log = logging.getLogger("playmystation.now")

# Докачка идёт вне bulkhead-таймаута /now: YT-трек может качаться минуту+.
DOWNLOAD_TIMEOUT = 120.0


async def _send_track_audio(message: Message, db_user: User, track: TrackDTO) -> None:
    """Фоновая отдача аудио после /now. Best-effort: тихо, без спама в чат.

    Порядок: кеш file_id (Redis + приватный канал) → докачка →
    отправка юзеру + складирование в канал для следующих раз.
    """
    cache_key = audio_cache_key(track)
    if cache_key is None:
        return
    # 1) повторная отдача по file_id без перекачивания
    file_id = await get_cached_audio_file_id(cache_key)
    if file_id:
        try:
            await message.answer_audio(audio=file_id, title=track.title, performer=track.artist)
            return
        except TelegramAPIError:
            log.info("stale audio file_id, re-downloading '%s'", track.title)
    # 2) докачка
    try:
        async with SessionFactory() as session:
            integrations = await repo.list_integrations(session, db_user.id)
            integ = next((i for i in integrations if i.provider == track.provider), None)
            if integ is None:
                return
            svc = await build_service(integ, session)
            if svc is None:
                return
            # Матчинг Spotify/Last.fm качает с YouTube: подкладываем куки
            # из YouTube-привязки юзера, иначе бан серверного IP.
            cookie_json = None
            if track.provider in ("spotify", "lastfm"):
                yt_integ = next((i for i in integrations if i.provider == "youtube"), None)
                if yt_integ is not None:
                    cookie_json = repo.decrypted_access(yt_integ)
            try:
                result = await asyncio.wait_for(
                    svc.download_track(track, cookie_json=cookie_json),
                    timeout=DOWNLOAD_TIMEOUT,
                )
            except (TimeoutError, Exception):  # noqa: BLE001 — докачка не обязана успевать
                log.info("download failed/timeout: %s '%s'", track.provider, track.title)
                return
            if result is None:
                return
            data, ext = result
            filename = safe_filename(track.artist, track.title, ext=ext)
            await message.answer_audio(
                BufferedInputFile(data, filename=filename),
                title=track.title,
                performer=track.artist,
            )
            # 3) складировать в канал для следующих раз
            await _store_to_cache_channel(message.bot, cache_key, data, filename, track)
    except Exception:
        log.exception("download task crashed")


async def _store_to_cache_channel(
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


def _schedule_download(message: Message, db_user: User, track: TrackDTO) -> None:
    asyncio.create_task(_send_track_audio(message, db_user, track))


def _schedule_platform_buttons(sent: Message, track: TrackDTO) -> None:
    if not track.track_url:
        return
    asyncio.create_task(_add_platform_buttons(sent, track))


async def _add_platform_buttons(sent: Message, track: TrackDTO) -> None:
    """Фоном найти тот же трек на других платформах и докинуть кнопки. Best-effort."""
    try:
        links = await match_platform_links(
            track.track_url, exclude=(track.provider,)
        )
    except Exception:
        log.info("songlink match failed for '%s'", track.title, exc_info=True)
        return
    if not links:
        return
    try:
        await sent.edit_reply_markup(
            reply_markup=track_kb(bool(track.preview_url), links)
        )
    except TelegramAPIError:
        log.info("songlink buttons edit failed (message gone?)")


async def _answer_now(message: Message, session: AsyncSession, db_user: User) -> None:
    integrations = await repo.list_integrations(session, db_user.id)
    if not integrations:
        await message.answer(
            "❌ Нет привязанных сервисов.\nОткрой /services и подключи хотя бы один.",
            reply_markup=now_empty_kb(),
        )
        return
    track = await resolve_now_playing(
        integrations, session, db_user.active_provider or "all", db_user.telegram_id
    )
    if track is None:
        await message.answer(
            "⏸️ Сейчас ничего не играет (или API не вернуло трек).\n"
            "Проверь, что музыка запущена, или смени активный сервис в /services.",
            reply_markup=now_empty_kb(),
        )
        return
    kb = track_kb(has_preview=bool(track.preview_url))
    if track.cover_url:
        sent = await message.answer_photo(
            photo=track.cover_url, caption=track_card(track), reply_markup=kb
        )
    else:
        sent = await message.answer(track_card(track), reply_markup=kb)
    _schedule_download(message, db_user, track)
    _schedule_platform_buttons(sent, track)


@router.message(Command("now", "np"))
async def cmd_now(message: Message, session: AsyncSession, db_user: User) -> None:
    await _answer_now(message, session, db_user)


@router.callback_query(F.data == "svc:now")
async def cb_now(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await cb.answer()
    # Callback не имеет message.answer с тем же контекстом — шлём новое сообщение
    integrations = await repo.list_integrations(session, db_user.id)
    if not integrations:
        await cb.message.answer("❌ Нет привязанных сервисов. Открой /services.")
        return
    track = await resolve_now_playing(
        integrations, session, db_user.active_provider or "all", db_user.telegram_id
    )
    if track is None:
        await cb.message.answer("⏸️ Сейчас ничего не играет.")
        return
    kb = track_kb(has_preview=bool(track.preview_url))
    if track.cover_url:
        sent = await cb.message.answer_photo(
            photo=track.cover_url, caption=track_card(track), reply_markup=kb
        )
    else:
        sent = await cb.message.answer(track_card(track), reply_markup=kb)
    _schedule_download(cb.message, db_user, track)
    _schedule_platform_buttons(sent, track)


@router.callback_query(F.data == "dl:preview")
async def cb_preview(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """Скачать и прислать превью текущего трека.

    Трек берём из Redis-кэша /now (TTL 20с): URL в callback_data не влезет
    (лимит 64 байта), поэтому переиспользуем закешированный результат.
    Легальность: только официальное 30-сек preview_url Spotify.
    """
    await cb.answer("⏬ Качаю превью…")
    integrations = await repo.list_integrations(session, db_user.id)
    if not integrations:
        await cb.message.answer("❌ Нет привязанных сервисов. Открой /services.")
        return
    track: TrackDTO | None = await resolve_now_playing(
        integrations, session, db_user.active_provider or "all", db_user.telegram_id
    )
    if track is None or not track.preview_url:
        await cb.message.answer(
            "ℹ️ Превью недоступно для этого трека.\n"
            "Spotify отдаёт превью не для всех треков."
        )
        return
    data = await fetch_audio_bytes(track.preview_url)
    if not data:
        await cb.message.answer("❌ Не получилось скачать превью. Попробуй позже.")
        return
    audio = BufferedInputFile(data, filename=safe_filename(track.artist, track.title))
    await cb.message.answer_audio(audio, title=track.title, performer=track.artist)
