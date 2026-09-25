"""Привязка Яндекс Музыки через /yandex <token>. Токен шифруется в БД."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repositories as repo
from app.db.models import User
from app.services.yandex import YandexMusicService

router = Router()


@router.message(Command("yandex"))
async def cmd_yandex(
    message: Message, command: CommandObject, session: AsyncSession, db_user: User
) -> None:
    token = (command.args or "").strip().strip('"').strip("'")
    if not token:
        await message.answer(
            "🔴 Пришли токен так:\n<code>/yandex &lt;твой_токен&gt;</code>"
        )
        return
    # Быстрая проверка токена перед сохранением
    svc = YandexMusicService(token)
    probe = await svc.get_currently_playing()
    # NOTE: probe может быть None просто потому что очередь пуста — это ОК.
    # Проверяем валидность отдельным лёгким вызовом библиотеки в thread.
    import asyncio as _aio

    def _check() -> bool:
        try:
            from yandex_music import Client

            Client(token).init()
            return True
        except Exception:
            return False

    valid = await _aio.to_thread(_check)
    if not valid:
        await message.answer("❌ Токен не подошёл. Проверь и попробуй ещё раз.")
        return

    await repo.upsert_integration(
        session, user_id=db_user.id, provider="yandex", access_token=token
    )
    await session.commit()
    hint = " (очередь пуста — запусти трек и проверь /now)" if probe is None else ""
    await message.answer(f"✅ Яндекс Музыка подключена{hint}. Активный сервис: {db_user.active_provider}.")
    # Удаляем сообщение с токеном из чата по возможности (гигиена секретов)
    try:
        await message.delete()
    except Exception:
        pass
