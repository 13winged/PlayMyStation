"""Привязка YouTube Music через /youtube <заголовки из браузера>.

Browser auth по документации ytmusicapi (без серверных OAuth-ключей):
пользователь копирует request headers из DevTools на music.youtube.com
(достаточно строк `cookie:` и `x-goog-authuser:`), бот превращает их
в auth-JSON через `ytmusicapi.setup` и хранит в БД в зашифрованном виде.
"""

from __future__ import annotations

import asyncio

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import invalidate_now_playing_cache
from app.db import repositories as repo
from app.db.models import User
from app.services.youtube import build_auth_json, check_auth

router = Router()

SETUP_HINT = (
    "▶️ <b>Подключение YouTube Music</b>\n\n"
    "1. Открой <code>music.youtube.com</code> в браузере и войди в аккаунт\n"
    "2. Открой DevTools (Ctrl+Shift+I) → вкладка Network, в фильтр введи "
    "<code>/browse</code>\n"
    "3. Обнови страницу (Ctrl+R), найди POST-запрос <code>browse?...</code>\n"
    "4. Скопируй заголовки ЦЕЛИКОМ (Firefox: правый клик → Copy → "
    "Copy Request Headers). Нужны в том числе строки "
    "<code>authorization: SAPISIDHASH...</code>, <code>cookie: ...</code> "
    "и <code>x-goog-authuser: ...</code> — по двум строкам не взлетит\n"
    "5. Пришли их боту одним сообщением:\n"
    "<code>/youtube &lt;заголовки&gt;</code>\n\n"
    "Заголовки хранятся в зашифрованном виде и действуют, пока жива сессия "
    "в браузере (обычно ~2 года)."
)


@router.message(Command("youtube", "ytmusic"))
async def cmd_youtube(
    message: Message, command: CommandObject, session: AsyncSession, db_user: User
) -> None:
    raw = (command.args or "").strip()
    if not raw:
        await message.answer(SETUP_HINT)
        return

    # Принимаем либо готовый auth-JSON, либо сырые заголовки из браузера.
    payload = raw.strip().strip('"').strip("'")
    if payload.startswith("{"):
        auth_json = payload
    else:
        try:
            auth_json = await asyncio.to_thread(build_auth_json, payload)
        except ValueError:
            await message.answer(
                "❌ Заголовки неполные: нужны ВСЕ заголовки запроса "
                "<code>/browse</code> целиком (включая "
                "<code>authorization: SAPISIDHASH...</code>). "
                "В DevTools: правый клик по запросу → Copy → "
                "Copy Request Headers → вставь всё как есть."
            )
            return

    valid = await check_auth(auth_json)
    if not valid:
        await message.answer(
            "❌ Заголовки не подошли (история не открылась). "
            "Скопируй свежие заголовки и попробуй ещё раз."
        )
        return

    await repo.upsert_integration(
        session, user_id=db_user.id, provider="youtube", access_token=auth_json
    )
    await session.commit()
    await invalidate_now_playing_cache(db_user.telegram_id)
    await message.answer("✅ YouTube Music подключён! Жми /now 🎵")
    # Удаляем сообщение с cookie из чата по возможности (гигиена секретов)
    try:
        await message.delete()
    except Exception:  # noqa: BLE001, S110 — удаление best-effort
        pass
