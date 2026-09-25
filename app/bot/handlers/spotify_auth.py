"""Ручная привязка Spotify через /spotify <code>.

Запасной путь на случай, когда OAuth-callback недоступен из браузера
(например, нет валидного HTTPS-сертификата на колбэк-домене):
пользователь копирует `code` из адресной строки после редиректа Spotify
и присылает его боту — обмен code→token делает сервер (исходящий HTTPS).
Код одноразовый и живёт ~10 минут.
"""

from __future__ import annotations

import datetime as dt
import html
import logging

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

log = logging.getLogger("playmystation.spotify_auth")

TOKEN_URL = "https://accounts.spotify.com/api/token"


@router.message(Command("spotify"))
async def cmd_spotify(
    message: Message, command: CommandObject, session: AsyncSession, db_user: User
) -> None:
    code = (command.args or "").strip().strip('"').strip("'").split()[0] if command.args else ""
    if not code:
        await message.answer(
            "🟢 Пришли код так:\n<code>/spotify &lt;код_из_адресной_строки&gt;</code>\n\n"
            "Где взять код:\n"
            "1. Нажми ➕ Spotify в /services и подтверди доступ\n"
            "2. Браузер перейдёт на страницу колбэка (она может не открыться — это ОК)\n"
            "3. Скопируй значение параметра <code>code=...</code> из адресной строки\n"
            "4. Пришли его этой командой (код одноразовый, живёт ~10 минут)"
        )
        return

    settings = get_settings()
    if not settings.spotify_client_id or not settings.spotify_client_secret:
        await message.answer("❌ Spotify OAuth не настроен на сервере (.env).")
        return

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.spotify_redirect_uri,
            },
            auth=(settings.spotify_client_id, settings.spotify_client_secret),
        )
    if resp.status_code != 200:
        # Spotify возвращает JSON вида {"error": "...", "error_description": "..."}.
        # Пишем полный ответ в лог, пользователю показываем только описание
        # (секретов там нет) — иначе причину отклонения не диагностировать.
        try:
            err = resp.json()
            err_desc = err.get("error_description") or err.get("error") or resp.text
        except Exception:  # noqa: BLE001 — не-JSON ответ
            err_desc = resp.text
        log.warning("Spotify token exchange failed: %s %s", resp.status_code, resp.text)
        safe_desc = html.escape(err_desc[:300], quote=False)
        await message.answer(
            "❌ Spotify отклонил код.\n"
            f"Причина: <code>{safe_desc}</code>\n\n"
            "Чаще всего это несовпадение redirect_uri: в обмене должен быть "
            "точно тот же URI, что в ссылке авторизации. Проверь "
            "SPOTIFY_REDIRECT_URI в настройках сервера."
        )
        return

    data = resp.json()
    expires_at = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=int(data.get("expires_in", 3600)))
    await repo.upsert_integration(
        session,
        user_id=db_user.id,
        provider="spotify",
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_at=expires_at,
    )
    await session.commit()
    await invalidate_now_playing_cache(db_user.telegram_id)
    await message.answer("✅ Spotify подключён! Жми /now 🎵")
    # Удаляем сообщение с кодом из чата (гигиена секретов)
    try:
        await message.delete()
    except Exception:  # noqa: BLE001, S110 — удаление best-effort
        pass
