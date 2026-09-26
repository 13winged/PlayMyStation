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
    if not username:
        integrations = await repo.list_integrations(session, db_user.id)
        if "lastfm" in {i.provider for i in integrations}:
            await repo.set_active_provider(session, db_user, "lastfm")
            await session.commit()
            await invalidate_now_playing_cache(db_user.telegram_id)
            await message.answer("🟪 Активный сервис: <b>Last.fm</b>. Жми /now 🎵")
            return
        await message.answer(
            "🟪 Пришли username так:\n<code>/lastfm &lt;твой_lastfm_username&gt;</code>\n\n"
            "Где взять: Paper Planes → Last.fm → Settings → профиль. "
            "Плюс свяжи Spotify → Last.fm (скробблинг), чтобы бот видел треки."
        )
        return

    settings = get_settings()
    if not settings.lastfm_api_key:
        await message.answer("❌ Last.fm API-ключ не настроен на сервере (.env).")
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
            await message.answer("❌ Last.fm не отвечает. Попробуй позже.")
            return
    if resp.status_code != 200 or "error" in resp.json():
        await message.answer(
            f"❌ Пользователь <code>{html.escape(username, quote=False)}</code> "
            "не найден на Last.fm. Проверь username."
        )
        return

    await repo.upsert_integration(
        session, user_id=db_user.id, provider="lastfm", access_token=None,
        service_user_id=username,
    )
    await session.commit()
    await invalidate_now_playing_cache(db_user.telegram_id)
    await message.answer(
        f"✅ Last.fm подключён (<code>{html.escape(username, quote=False)}</code>). Жми /now 🎵"
    )
