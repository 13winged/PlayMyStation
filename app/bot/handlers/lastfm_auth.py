"""Привязка Last.fm через /lastfm <username>. OAuth не нужен — только username.

Токены не хранятся: username кладётся в integrations.service_user_id,
а API-ключ — один на всех, в LASTFM_API_KEY на сервере.
"""

from __future__ import annotations

import html

import httpx
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.i18n import lang_of, t
from app.core.config import get_settings
from app.core.redis import invalidate_now_playing_cache
from app.db import repositories as repo
from app.db.models import User

router = Router()


@router.message(Command("lastfm"))
async def cmd_lastfm(
    message: Message, command: CommandObject, session: AsyncSession, db_user: User
) -> None:
    username = (command.args or "").strip().strip('"').strip("'").split()[0] if command.args else ""
    lang = lang_of(db_user)
    if not username:
        integrations = await repo.list_integrations(session, db_user.id)
        if "lastfm" in {i.provider for i in integrations}:
            await repo.set_active_provider(session, db_user, "lastfm")
            await session.commit()
            await invalidate_now_playing_cache(db_user.telegram_id)
            await message.answer(t(lang, "lfm_active"))
            return
        await message.answer(t(lang, "lfm_hint"))
        return

    settings = get_settings()
    if not settings.lastfm_api_key:
        await message.answer(t(lang, "lfm_no_key"))
        return

    # Проверяем, что юзер существует (user.getrecenttracks вернёт error=6 если нет)
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                "https://ws.audioscrobbler.com/2.0/",
                params={
                    "method": "user.getrecenttracks",
                    "user": username,
                    "api_key": settings.lastfm_api_key,
                    "format": "json",
                    "limit": 1,
                },
            )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError):
            await message.answer(t(lang, "lfm_no_network"))
            return
    if resp.status_code != 200 or "error" in resp.json():
        await message.answer(
            t(lang, "lfm_not_found", username=html.escape(username, quote=False))
        )
        return

    await repo.upsert_integration(
        session, user_id=db_user.id, provider="lastfm", access_token=None,
        service_user_id=username,
    )
    await session.commit()
    await invalidate_now_playing_cache(db_user.telegram_id)
    await message.answer(
        t(lang, "lfm_ok", username=html.escape(username, quote=False))
    )
