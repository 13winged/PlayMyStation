"""Ручная привязка SoundCloud через /soundcloud <code>.

Запасной путь на случай, когда OAuth-callback недоступен из браузера:
пользователь копирует `code` из адресной строки после редиректа SoundCloud
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

log = logging.getLogger("playmystation.soundcloud_auth")

TOKEN_URL = "https://secure.soundcloud.com/oauth/token"


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


@router.message(Command("soundcloud"))
async def cmd_soundcloud(
    message: Message, command: CommandObject, session: AsyncSession, db_user: User
) -> None:
    raw_args = (command.args or "").strip()
    if not raw_args:
        await message.answer(
            "🟠 Пришли код так:\n<code>/soundcloud <код_из_адресной_строки></code>\n\n"
            "Где взять код:\n"
            "1. Нажми ➕ SoundCloud в /services и подтверди доступ\n"
            "2. Браузер перейдёт на страницу колбэка (она может не открыться — это ОК)\n"
            "3. Скопируй значение параметра <code>code=...</code> из адресной строки\n"
            "4. Пришли его этой командой (код одноразовый, живёт ~10 минут)"
        )
        return
    # Пользователь может вставить: голый код, код с хвостом &state=...,
    # или целую callback-ссылку — извлекаем чистое значение code.
    code, state = extract_code_and_state(raw_args)
    if not code:
        await message.answer("❌ Не нашёл код. Пришли <code>/soundcloud <код></code>.")
        return
    # Если прислали и state — сверяем, что код выдан именно этому юзеру.
    if state is not None and state != str(db_user.telegram_id):
        await message.answer(
            "❌ Этот код выдан для другого Telegram-аккаунта "
            f"(state={state}).\nПройди авторизацию заново с этого аккаунта."
        )
        return

    settings = get_settings()
    if not settings.soundcloud_client_id or not settings.soundcloud_client_secret:
        await message.answer("❌ SoundCloud OAuth не настроен на сервере (.env).")
        return

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": settings.soundcloud_client_id,
                "client_secret": settings.soundcloud_client_secret,
                "redirect_uri": settings.soundcloud_redirect_uri,
            },
        )
    if resp.status_code != 200:
        # SoundCloud возвращает JSON вида {"error": "...", "error_description": "..."}.
        try:
            err = resp.json()
            err_desc = err.get("error_description") or err.get("error") or resp.text
        except Exception:  # noqa: BLE001 — не-JSON ответ
            err_desc = resp.text
        log.warning("SoundCloud token exchange failed: %s %s", resp.status_code, resp.text)
        safe_desc = html.escape(err_desc[:300], quote=False)
        await message.answer(
            "❌ SoundCloud отклонил код.\n"
            f"Причина: <code>{safe_desc}</code>\n\n"
            "Чаще всего это несовпадение redirect_uri: в обмене должен быть "
            "точно тот же URI, что в ссылке авторизации. Проверь "
            "SOUNDCLOUD_REDIRECT_URI в настройках сервера."
        )
        return

    data = resp.json()
    expires_at = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=int(data.get("expires_in", 3600)))
    await repo.upsert_integration(
        session,
        user_id=db_user.id,
        provider="soundcloud",
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_at=expires_at,
    )
    await session.commit()
    await invalidate_now_playing_cache(db_user.telegram_id)
    await message.answer("✅ SoundCloud подключён! Жми /now 🎵")
    # Удаляем сообщение с кодом из чата (гигиена секретов)
    try:
        await message.delete()
    except Exception:  # noqa: BLE001, S110 — удаление best-effort
        pass