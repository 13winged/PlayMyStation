"""Команда /now и /np: опрос активного сервиса или всех (режим ALL).

После карточки трека бот фоном докачивает аудио и присылает его
следующим сообщением (best-effort): Яндекс/YouTube — полный трек,
Spotify/Last.fm — YouTube-матчинг по метаданным (у Spotify фолбэк preview).
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.delivery import fetch_and_send
from app.bot.editing import edit_markup_safe
from app.bot.formatters import track_card
from app.bot.i18n import lang_of, t
from app.bot.keyboards import now_empty_kb, track_kb
from app.core.redis import get_cached_now_playing, invalidate_now_playing_cache
from app.db import repositories as repo
from app.db.models import User
from app.services.audio import fetch_audio_bytes, safe_filename
from app.services.base import TrackDTO
from app.services.crosslink import match_same_track
from app.services.factory import _safe_get_playing, build_service, resolve_now_playing
from app.services.spotify import SpotifyService

router = Router()

log = logging.getLogger("playmystation.now")


async def _send_track_audio(message: Message, db_user: User, track: TrackDTO) -> None:
    """Фоновая отдача аудио после /now. Best-effort: тихо, без спама в чат."""
    try:
        await fetch_and_send(message, db_user, track)
    except Exception:
        log.exception("download task crashed")


def _schedule_download(message: Message, db_user: User, track: TrackDTO) -> None:
    asyncio.create_task(_send_track_audio(message, db_user, track))


def _yandex_token(integrations: list) -> str | None:
    """Токен Яндекс-привязки юзера для поиска (дешифрованный)."""
    integ = next((i for i in integrations if i.provider == "yandex"), None)
    return repo.decrypted_access(integ) if integ is not None else None


def _schedule_platform_buttons(
    sent: Message, track: TrackDTO, lang: str, yandex_token: str | None
) -> None:
    asyncio.create_task(_add_platform_buttons(sent, track, lang, yandex_token))


async def _add_platform_buttons(
    sent: Message, track: TrackDTO, lang: str, yandex_token: str | None
) -> None:
    """Фоном найти тот же трек на других платформах и докинуть кнопки. Best-effort."""
    try:
        links = await match_same_track(track, yandex_token)
    except Exception:
        log.info("crosslink match failed for '%s'", track.title, exc_info=True)
        return
    if not links:
        return
    try:
        await edit_markup_safe(
            sent,
            track_kb(
                bool(track.preview_url),
                links,
                lang,
                controls=(track.provider == "spotify"),
                playing=track.is_playing,
            ),
        )
    except TelegramAPIError:
        log.info("platform buttons edit failed (message gone?)")


async def _answer_now(message: Message, session: AsyncSession, db_user: User) -> None:
    lang = lang_of(db_user)
    integrations = await repo.list_integrations(session, db_user.id)
    if not integrations:
        await message.answer(
            t(lang, "now_no_services"),
            reply_markup=now_empty_kb(lang),
        )
        return
    track = await resolve_now_playing(
        integrations, session, db_user.active_provider or "all", db_user.telegram_id
    )
    if track is None:
        await message.answer(
            t(lang, "now_nothing"),
            reply_markup=now_empty_kb(lang),
        )
        return
    kb = track_kb(
        has_preview=bool(track.preview_url),
        lang=lang,
        controls=(track.provider == "spotify"),
        playing=track.is_playing,
    )
    if track.cover_url:
        sent = await message.answer_photo(
            photo=track.cover_url, caption=track_card(track, lang), reply_markup=kb
        )
    else:
        sent = await message.answer(track_card(track, lang), reply_markup=kb)
    _schedule_download(message, db_user, track)
    _schedule_platform_buttons(sent, track, lang, _yandex_token(integrations))


@router.message(Command("now", "np"))
async def cmd_now(message: Message, session: AsyncSession, db_user: User) -> None:
    await _answer_now(message, session, db_user)


@router.callback_query(F.data == "svc:now")
async def cb_now(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await cb.answer()
    lang = lang_of(db_user)
    # Callback не имеет message.answer с тем же контекстом — шлём новое сообщение
    integrations = await repo.list_integrations(session, db_user.id)
    if not integrations:
        await cb.message.answer(t(lang, "now_no_services"))
        return
    track = await resolve_now_playing(
        integrations, session, db_user.active_provider or "all", db_user.telegram_id
    )
    if track is None:
        await cb.message.answer(t(lang, "now_nothing_short"))
        return
    kb = track_kb(
        has_preview=bool(track.preview_url),
        lang=lang,
        controls=(track.provider == "spotify"),
        playing=track.is_playing,
    )
    if track.cover_url:
        sent = await cb.message.answer_photo(
            photo=track.cover_url, caption=track_card(track, lang), reply_markup=kb
        )
    else:
        sent = await cb.message.answer(track_card(track, lang), reply_markup=kb)
    _schedule_download(cb.message, db_user, track)
    _schedule_platform_buttons(sent, track, lang, _yandex_token(integrations))


@router.callback_query(F.data == "dl:preview")
async def cb_preview(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    """Скачать и прислать превью текущего трека.

    Трек берём из Redis-кэша /now (TTL 20с): URL в callback_data не влезет
    (лимит 64 байта), поэтому переиспользуем закешированный результат.
    Легальность: только официальное 30-сек preview_url Spotify.
    """
    lang = lang_of(db_user)
    await cb.answer("⏬ Качаю превью…")
    integrations = await repo.list_integrations(session, db_user.id)
    if not integrations:
        await cb.message.answer(t(lang, "now_no_services"))
        return
    track: TrackDTO | None = await resolve_now_playing(
        integrations, session, db_user.active_provider or "all", db_user.telegram_id
    )
    if track is None or not track.preview_url:
        await cb.message.answer(t(lang, "preview_unavailable"))
        return
    data = await fetch_audio_bytes(track.preview_url)
    if not data:
        await cb.message.answer(t(lang, "preview_failed"))
        return
    audio = BufferedInputFile(data, filename=safe_filename(track.artist, track.title))
    await cb.message.answer_audio(audio, title=track.title, performer=track.artist)


# ---------- Управление воспроизведением Spotify ----------


async def _spotify_ctx(
    session: AsyncSession, db_user: User
) -> tuple[SpotifyService | None, TrackDTO | None]:
    """Spotify-сервис юзера + текущий трек (сначала Redis, иначе опрос)."""
    integrations = await repo.list_integrations(session, db_user.id)
    integ = next((i for i in integrations if i.provider == "spotify"), None)
    if integ is None:
        return None, None
    svc = await build_service(integ, session)
    if not isinstance(svc, SpotifyService):
        return None, None
    track = await get_cached_now_playing(db_user.telegram_id)
    if track is None or track.provider != "spotify":
        track = await _safe_get_playing(svc)
    return svc, track


async def _answer_control(
    cb: CallbackQuery, db_user: User, status: str, ok_key: str
) -> None:
    lang = lang_of(db_user)
    if status == "ok":
        await invalidate_now_playing_cache(db_user.telegram_id)
        await cb.answer(t(lang, ok_key))
    else:
        await cb.answer(t(lang, "ctl_failed"), show_alert=True)


@router.callback_query(F.data == "ctl:toggle")
async def cb_control_toggle(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    svc, track = await _spotify_ctx(session, db_user)
    if svc is None:
        await cb.answer(t(lang_of(db_user), "ctl_no_spotify"), show_alert=True)
        return
    playing = bool(track and track.is_playing)
    status = await svc.set_playing(not playing)
    await _answer_control(cb, db_user, status, "ctl_resumed" if not playing else "ctl_paused")


@router.callback_query(F.data == "ctl:next")
async def cb_control_next(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    svc, _ = await _spotify_ctx(session, db_user)
    if svc is None:
        await cb.answer(t(lang_of(db_user), "ctl_no_spotify"), show_alert=True)
        return
    await _answer_control(cb, db_user, await svc.skip("next"), "ctl_skipped_next")


@router.callback_query(F.data == "ctl:prev")
async def cb_control_prev(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    svc, _ = await _spotify_ctx(session, db_user)
    if svc is None:
        await cb.answer(t(lang_of(db_user), "ctl_no_spotify"), show_alert=True)
        return
    await _answer_control(cb, db_user, await svc.skip("previous"), "ctl_skipped_prev")


@router.callback_query(F.data == "ctl:like")
async def cb_control_like(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    svc, track = await _spotify_ctx(session, db_user)
    if svc is None or track is None:
        await cb.answer(t(lang_of(db_user), "ctl_no_spotify"), show_alert=True)
        return
    await _answer_control(cb, db_user, await svc.like_track(track), "ctl_liked")
