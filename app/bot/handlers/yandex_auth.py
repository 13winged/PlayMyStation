"""Привязка Яндекс Музыки через /yandex <token>. Токен шифруется в БД."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import invalidate_now_playing_cache
from app.db import repositories as repo
from app.db.models import User
from app.services.yandex import YandexMusicService

router = Router()


def extract_yandex_token(raw_args: str) -> str:
    """Извлечь чистый OAuth-токен из ввода пользователя.

    Принимает: голый токен, токен с хвостом `&token_type=...&expires_in=...`,
    целиком callback-фрагмент (`access_token=...&...`).
    """
    token = raw_args.strip().split()[0] if raw_args.strip() else ""
    if "access_token=" in token:
        token = token.split("access_token=", 1)[1]
    token = token.split("&")[0].strip().strip('"').strip("'")
    return token


@router.message(Command("yandex"))
async def cmd_yandex(
    message: Message, command: CommandObject, session: AsyncSession, db_user: User
) -> None:
    token = extract_yandex_token(command.args or "")
    if not token:
        integrations = await repo.list_integrations(session, db_user.id)
        if "yandex" in {i.provider for i in integrations}:
            await repo.set_active_provider(session, db_user, "yandex")
            await session.commit()
            await invalidate_now_playing_cache(db_user.telegram_id)
            await message.answer("🔴 Активный сервис: <b>Яндекс Музыка</b>. Жми /now 🎵")
            return
        await message.answer("🔴 Пришли токен так:\n<code>/yandex &lt;твой_токен&gt;</code>")
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
        except Exception:  # noqa: BLE001 — любая ошибка = невалидный токен
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
    await message.answer(
        f"✅ Яндекс Музыка подключена{hint}. Активный сервис: {db_user.active_provider}."
    )
    # Удаляем сообщение с токеном из чата по возможности (гигиена секретов)
    try:
        await message.delete()
    except Exception:  # noqa: BLE001, S110 — удаление best-effort
        pass
