"""Привязка YouTube Music через /youtube <заголовки из браузера>.

Browser auth по документации ytmusicapi (без серверных OAuth-ключей):
пользователь копирует request headers из DevTools на music.youtube.com,
бот превращает их в auth-JSON через `ytmusicapi.setup` и хранит в БД
в зашифрованном виде. Без аргументов и с привязанным сервисом —
переключение активного режима.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.i18n import lang_of, t
from app.core.db import SessionFactory
from app.core.redis import (
    delete_pending_youtube_oauth,
    get_pending_youtube_oauth,
    invalidate_now_playing_cache,
    set_pending_youtube_oauth,
)
from app.db import repositories as repo
from app.db.models import User
from app.services.youtube import build_auth_json, check_auth, validate_auth_json
from app.services.youtube_oauth import (
    build_oauth_token_dict,
    exchange_once,
    oauth_configured,
    server_oauth_credentials,
    start_device_flow,
)

router = Router()

log = logging.getLogger("playmystation.youtube_auth")


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
        # Свободна OAuth-привязка без DevTools — пробуем её первой.
        if oauth_configured():
            await _start_oauth_flow(message, db_user, lang)
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
    await repo.log_audit(session, db_user.id, db_user.telegram_id, "connect", "youtube", "headers")
    await session.commit()
    await invalidate_now_playing_cache(db_user.telegram_id)
    await message.answer(t(lang, "yt_ok"))
    # Удаляем сообщение с cookie из чата по возможности (гигиена секретов)
    try:
        await message.delete()
    except Exception:  # noqa: BLE001, S110 — удаление best-effort
        pass


async def _start_oauth_flow(message: Message, db_user: User, lang: str) -> None:
    """Шаг 1 device-flow: показать ссылку + код, запустить фоновый поллинг."""
    try:
        flow = await start_device_flow()
    except Exception:
        log.warning("YouTube OAuth get_code failed", exc_info=True)
        await message.answer(t(lang, "yt_oauth_error"))
        return
    generation = uuid.uuid4().hex
    ttl = int(flow["expires_in"])
    await set_pending_youtube_oauth(
        db_user.telegram_id,
        {
            "generation": generation,
            "device_code": flow["device_code"],
            "interval": int(flow["interval"]),
            "deadline": time.time() + ttl - 30,
        },
        ttl,
    )
    minutes = max(1, ttl // 60)
    await message.answer(
        t(
            lang,
            "yt_oauth_start",
            url=flow["verification_url"],
            code=flow["user_code"],
            minutes=minutes,
        )
    )
    asyncio.create_task(_poll_oauth_flow(message, db_user, flow, generation, lang))


async def _poll_oauth_flow(
    message: Message, db_user: User, flow: dict, generation: str, lang: str
) -> None:
    """Фон: ждать подтверждения юзера, обменять код на токен, сохранить."""
    telegram_id = db_user.telegram_id
    creds = server_oauth_credentials()
    if creds is None:  # конфиг сняли на ходу — сворачиваемся
        return
    interval = int(flow["interval"])
    deadline = time.time() + int(flow["expires_in"]) - 30
    while time.time() < deadline:
        await asyncio.sleep(interval)
        pending = await get_pending_youtube_oauth(telegram_id)
        if pending is None or pending.get("generation") != generation:
            return  # superseded: юзер перезапустил /youtube
        status, payload = await asyncio.to_thread(
            exchange_once, creds, flow["device_code"]
        )
        if status == "pending":
            continue
        if status == "slow_down":
            interval += 5
            continue
        if status == "ok" and payload:
            token_json = json.dumps(build_oauth_token_dict(payload))
            async with SessionFactory() as session:
                user = await repo.get_or_create_user(session, telegram_id)
                await repo.upsert_integration(
                    session, user_id=user.id, provider="youtube", access_token=token_json
                )
                await repo.log_audit(
                    session, user.id, telegram_id, "connect", "youtube", "oauth device"
                )
                await session.commit()
            await delete_pending_youtube_oauth(telegram_id)
            await invalidate_now_playing_cache(telegram_id)
            await message.answer(t(lang, "yt_oauth_ok"))
            return
        await delete_pending_youtube_oauth(telegram_id)
        if status == "denied":
            await message.answer(t(lang, "yt_oauth_denied"))
        elif status == "expired":
            await message.answer(t(lang, "yt_oauth_expired"))
        else:
            log.warning("YouTube OAuth exchange failed: %s", payload)
            await message.answer(t(lang, "yt_oauth_error"))
        return
    await delete_pending_youtube_oauth(telegram_id)
    await message.answer(t(lang, "yt_oauth_expired"))
