"""Команда /now и /np: опрос активного сервиса или всех (режим ALL)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatters import track_card
from app.bot.keyboards import now_empty_kb, track_kb
from app.db import repositories as repo
from app.db.models import User
from app.services.audio import fetch_audio_bytes, safe_filename
from app.services.base import TrackDTO
from app.services.factory import resolve_now_playing

router = Router()


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
        await message.answer_photo(
            photo=track.cover_url, caption=track_card(track), reply_markup=kb
        )
    else:
        await message.answer(track_card(track), reply_markup=kb)


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
        await cb.message.answer_photo(
            photo=track.cover_url, caption=track_card(track), reply_markup=kb
        )
    else:
        await cb.message.answer(track_card(track), reply_markup=kb)


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
