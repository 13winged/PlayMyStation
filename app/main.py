"""Точка входа: aiogram polling + FastAPI (uvicorn) в одном asyncio-процессе."""
from __future__ import annotations

import asyncio
import logging

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from app.bot.handlers import now as now_handlers
from app.bot.handlers import start as start_handlers
from app.bot.handlers import yandex_auth as yandex_handlers
from app.bot.middlewares import DbSessionMiddleware, EnsureUserMiddleware
from app.core.config import get_settings
from app.core.db import SessionFactory, engine
from app.core.redis import get_redis
from app.db.models import Base
from app.web.app import create_web_app

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("playmystation")


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("DB tables ensured")


def create_dispatcher() -> Dispatcher:
    # Продакшн: RedisStorage; фолбэк — MemoryStorage
    try:
        settings = get_settings()
        storage = RedisStorage.from_url(settings.redis_url)
    except Exception:
        storage = MemoryStorage()  # type: ignore[assignment]
    dp = Dispatcher(storage=storage)
    dp.message.middleware(DbSessionMiddleware(SessionFactory))
    dp.callback_query.middleware(DbSessionMiddleware(SessionFactory))
    dp.message.middleware(EnsureUserMiddleware())
    dp.callback_query.middleware(EnsureUserMiddleware())
    dp.include_routers(start_handlers.router, now_handlers.router, yandex_handlers.router)
    return dp


async def run_bot() -> None:
    settings = get_settings()
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = create_dispatcher()
    await get_redis()  # прогрев соединения
    log.info("Bot polling started")
    await dp.start_polling(bot)


async def run_web() -> None:
    settings = get_settings()
    app = create_web_app()
    server = uvicorn.Server(
        uvicorn.Config(app, host=settings.web_host, port=settings.web_port, log_level="info")
    )
    log.info("Web (OAuth callbacks) started on %s:%s", settings.web_host, settings.web_port)
    await server.serve()


async def main() -> None:
    await init_db()
    await asyncio.gather(run_bot(), run_web())


if __name__ == "__main__":
    asyncio.run(main())
