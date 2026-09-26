"""Привязка YouTube Music через /youtube <заголовки из браузера>.

Browser auth по документации ytmusicapi (без серверных OAuth-ключей):
пользователь копирует request headers из DevTools на music.youtube.com,
бот превращает их в auth-JSON через `ytmusicapi.setup` и хранит в БД
в зашифрованном виде. Без аргументов и с привязанным сервисом —
переключение активного режима.
"""

from __future__ import annotations

import asyncio

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.i18n import lang_of, t
from app.core.redis import invalidate_now_playing_cache
from app.db import repositories as repo
from app.db.models import User
from app.services.youtube import build_auth_json, check_auth, validate_auth_json

router = Router()


@router.message(Command("youtube", "ytmusic"))
async def cmd_youtube(
    message: Message, command: CommandObject, session: AsyncSession, db_user: User
) -> None:
    lang = lang_of(db_user)
    raw = (command.args or "").strip()
    if not raw:
        integrations = await repo.list_integrations(session, db_user.id)
        if "youtube" in {i.provider for i in integrations}:
            await repo.set_active_provider(session, db_user, "youtube")
            await session.commit()
            await invalidate_now_playing_cache(db_user.telegram_id)
            await message.answer(t(lang, "yt_active"))
            return
        await message.answer(t(lang, "yt_hint"))
        return

    # Принимаем либо готовый auth-JSON, либо сырые заголовки из браузера.
    payload = raw.strip().strip('"').strip("'")
    try:
        if payload.startswith("{"):
            auth_json = payload
            validate_auth_json(auth_json)
        else:
            auth_json = await asyncio.to_thread(build_auth_json, payload)
    except (ValueError, TypeError) as e:
        detail = str(e)
        if "3PAPISID" in detail:
            await message.answer(t(lang, "yt_not_logged_in"))
        else:
            await message.answer(t(lang, "yt_incomplete"))
        return

    valid = await check_auth(auth_json)
    if not valid:
        await message.answer(t(lang, "yt_check_failed"))
        return

    await repo.upsert_integration(
        session, user_id=db_user.id, provider="youtube", access_token=auth_json
    )
    await session.commit()
    await invalidate_now_playing_cache(db_user.telegram_id)
    await message.answer(t(lang, "yt_ok"))
    # Удаляем сообщение с cookie из чата по возможности (гигиена секретов)
    try:
        await message.delete()
    except Exception:  # noqa: BLE001, S110 — удаление best-effort
        pass
