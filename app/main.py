"""Точка входа: aiogram polling + FastAPI (uvicorn) в одном asyncio-процессе."""

from __future__ import annotations

import asyncio
import logging
import os

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from alembic.config import Config

from alembic import command
from app.bot.handlers import now as now_handlers
from app.bot.handlers import start as start_handlers
from app.bot.handlers import yandex_auth as yandex_handlers
from app.bot.middlewares import DbSessionMiddleware, EnsureUserMiddleware
from app.core.config import get_settings
from app.core.db import SessionFactory
from app.core.redis import get_redis
from app.web.app import create_web_app

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("playmystation")


def run_alembic_upgrade() -> None:
    """Run alembic upgrade to head."""
    alembic_cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    # Override sqlalchemy.url from settings (asyncpg) to sync driver for alembic
    settings = get_settings()
    sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    alembic_cfg.set_main_option("sqlalchemy.url", sync_url)
    command.upgrade(alembic_cfg, "head")
    log.info("DB migrations applied")


async def init_db() -> None:
    # Run alembic in thread pool since it's synchronous
    await asyncio.to_thread(run_alembic_upgrade)


def create_dispatcher() -> Dispatcher:
    # Продакшн: RedisStorage; фолбэк — MemoryStorage
    try:
        settings = get_settings()
        storage = RedisStorage.from_url(settings.redis_url)
    except Exception:  # noqa: BLE001 — нет Redis = MemoryStorage
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
