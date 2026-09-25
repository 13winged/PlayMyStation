"""Middlewares: проброс AsyncSession и обеспечение User в handler data."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import repositories as repo


class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self._factory() as session:
            data["session"] = session
            result = await handler(event, data)
            # коммит на усмотрение хэндлеров; здесь не коммитим автоматически
            return result


class EnsureUserMiddleware(BaseMiddleware):
    """Создаёт User по telegram_id если его нет, кладёт в data['db_user']."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session: AsyncSession | None = data.get("session")
        tg_user = data.get("event_from_user")
        if session is not None and tg_user is not None:
            db_user = await repo.get_or_create_user(session, tg_user.id)
            await session.commit()
            data["db_user"] = db_user
        return await handler(event, data)
