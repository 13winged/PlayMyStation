"""Ручная привязка Spotify через /spotify <code>.

Запасной путь на случай, когда OAuth-callback недоступен из браузера
(например, нет валидного HTTPS-сертификата на колбэк-домене):
пользователь копирует `code` из адресной строки после редиректа Spotify
и присылает его боту — обмен code→token делает сервер (исходящий HTTPS).
Код одноразовый и живёт ~10 минут.
Без аргументов и с привязанным сервисом — переключение активного режима.
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

from app.bot.i18n import lang_of, t
from app.core.config import get_settings
from app.core.redis import invalidate_now_playing_cache
from app.db import repositories as repo
from app.db.models import User

router = Router()

log = logging.getLogger("playmystation.spotify_auth")

TOKEN_URL = "https://accounts.spotify.com/api/token"


def extract_code_and_state(raw_args: str) -> tuple[str, str | None]:
    """Извлечь чистый code (и опциональный state) из ввода пользователя.

    Принимает: голый код, код с хвостом `&state=...`, целую callback-ссылку.
    """
    token = raw_args.strip().split()[0] if raw_args.strip() else ""
    if "code=" in token:
        token = token.split("code=", 1)[1]
    code = token.split("&")[0].strip().strip('"').strip("'")
    state = None
    if "state=" in raw_args:
        state = raw_args.split("state=", 1)[1].split("&")[0].split()[0].strip()
    return code, state


@router.message(Command("spotify"))
async def cmd_spotify(
    message: Message, command: CommandObject, session: AsyncSession, db_user: User
) -> None:
    lang = lang_of(db_user)
    raw_args = (command.args or "").strip()
    if not raw_args:
        integrations = await repo.list_integrations(session, db_user.id)
        if "spotify" in {i.provider for i in integrations}:
            await repo.set_active_provider(session, db_user, "spotify")
            await session.commit()
            await invalidate_now_playing_cache(db_user.telegram_id)
            await message.answer(t(lang, "sp_active"))
            return
        await message.answer(t(lang, "sp_hint"))
        return
    # Пользователь может вставить: голый код, код с хвостом &state=...,
    # или целую callback-ссылку — извлекаем чистое значение code.
    code, state = extract_code_and_state(raw_args)
    if not code:
        await message.answer(t(lang, "sp_no_code"))
        return
    # Если прислали и state — сверяем, что код выдан именно этому юзеру.
    if state is not None and state != str(db_user.telegram_id):
        await message.answer(t(lang, "sp_wrong_state", state=state))
        return

    settings = get_settings()
    if not settings.spotify_client_id or not settings.spotify_client_secret:
        await message.answer(t(lang, "sp_no_oauth"))
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
        await message.answer(t(lang, "sp_rejected", reason=safe_desc))
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
    await repo.log_audit(session, db_user.id, db_user.telegram_id, "connect", "spotify", "manual code")
    await session.commit()
    await invalidate_now_playing_cache(db_user.telegram_id)
    await message.answer(t(lang, "sp_ok"))
    # Удаляем сообщение с кодом из чата (гигиена секретов)
    try:
        await message.delete()
    except Exception:  # noqa: BLE001, S110 — удаление best-effort
        pass
