"""Команда /now и /np: опрос активного сервиса или всех (режим ALL)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatters import track_card
from app.bot.keyboards import now_empty_kb
from app.db import repositories as repo
from app.db.models import User
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
    if track.cover_url:
        await message.answer_photo(photo=track.cover_url, caption=track_card(track))
    else:
        await message.answer(track_card(track))


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
    if track.cover_url:
        await cb.message.answer_photo(photo=track.cover_url, caption=track_card(track))
    else:
        await cb.message.answer(track_card(track))
