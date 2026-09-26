"""Точка входа: aiogram (polling или webhook) + FastAPI (uvicorn) в одном asyncio-процессе."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from contextlib import suppress

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from alembic.config import Config

from alembic import command
from app.bot.commands import setup_bot_meta
from app.bot.handlers import lang as lang_handlers
from app.bot.handlers import lastfm_auth as lastfm_handlers
from app.bot.handlers import now as now_handlers
from app.bot.handlers import spotify_auth as spotify_handlers
from app.bot.handlers import start as start_handlers
from app.bot.handlers import yandex_auth as yandex_handlers
from app.bot.handlers import youtube_auth as youtube_handlers
from app.bot.middlewares import DbSessionMiddleware, EnsureUserMiddleware, MetricsMiddleware
from app.core.config import get_settings
from app.core.db import SessionFactory
from app.core.observability import configure_structlog, init_sentry
from app.core.redis import close_redis, get_redis
from app.services.lastfm import close_lastfm_client
from app.services.spotify import close_spotify_client
from app.web.app import create_web_app, set_webhook_bot, set_webhook_dispatcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("playmystation")


def setup_logging() -> None:
    """(Пере)настроить логирование.

    Alembic вызывает logging.config.fileConfig(), который сносит хендлеры
    root-логгера и ставит level=WARNING — после миграций наши INFO-логи
    глохнут. Поэтому перенастраиваемся заново (force=True).
    Плюс конфигурируем structlog (JSON при LOG_FORMAT=json).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    configure_structlog()


def run_alembic_upgrade() -> None:
    """Run alembic upgrade to head."""
    alembic_cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    settings = get_settings()
    sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    alembic_cfg.set_main_option("sqlalchemy.url", sync_url)
    command.upgrade(alembic_cfg, "head")
    log.info("DB migrations applied")


async def init_db() -> None:
    await asyncio.to_thread(run_alembic_upgrade)


def create_dispatcher() -> Dispatcher:
    try:
        settings = get_settings()
        storage = RedisStorage.from_url(settings.redis_url)
    except Exception:  # noqa: BLE001
        storage = MemoryStorage()  # type: ignore[assignment]
    dp = Dispatcher(storage=storage)
    dp.update.middleware(MetricsMiddleware())
    dp.message.middleware(DbSessionMiddleware(SessionFactory))
    dp.callback_query.middleware(DbSessionMiddleware(SessionFactory))
    dp.message.middleware(EnsureUserMiddleware())
    dp.callback_query.middleware(EnsureUserMiddleware())
    dp.include_routers(
        start_handlers.router,
        now_handlers.router,
        yandex_handlers.router,
        spotify_handlers.router,
        youtube_handlers.router,
        lastfm_handlers.router,
        lang_handlers.router,
    )
    return dp


async def setup_webhook(bot: Bot) -> None:
    """Установить webhook для бота."""
    settings = get_settings()
    if not settings.use_webhook:
        return

    webhook_url = f"{settings.webhook_url.rstrip('/')}{settings.webhook_path}"
    log.info("Setting webhook: %s", webhook_url)

    await bot.set_webhook(
        url=webhook_url,
        secret_token=settings.webhook_secret if settings.webhook_secret else None,
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
    )
    log.info("Webhook set successfully")


async def delete_webhook(bot: Bot) -> None:
    """Удалить webhook (возврат к polling не нужен, просто чистим)."""
    settings = get_settings()
    if not settings.use_webhook:
        return

    log.info("Deleting webhook...")
    await bot.delete_webhook(drop_pending_updates=False)
    log.info("Webhook deleted")


async def run_polling(bot: Bot, dp: Dispatcher) -> None:
    """Запуск бота в режиме polling."""
    log.info("Starting bot in POLLING mode")
    # Если раньше стоял webhook — снимаем, иначе Telegram продолжит слать
    # апдейты на URL вместо выдачи через getUpdates.
    await bot.delete_webhook(drop_pending_updates=True)
    await get_redis()
    await dp.start_polling(bot)


async def run_webhook_mode(bot: Bot, dp: Dispatcher) -> None:
    """Запуск бота в режиме webhook (polling не запускаем, просто держим процесс)."""
    log.info("Starting bot in WEBHOOK mode")
    await get_redis()
    await setup_webhook(bot)

    # Держим процесс живым, ждём сигнал завершения
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        log.info("Received shutdown signal")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, _signal_handler)

    await stop_event.wait()
    log.info("Shutdown signal received, stopping...")


async def run_web_server() -> None:
    """Запуск FastAPI (uvicorn)."""
    settings = get_settings()
    app = create_web_app()
    config = uvicorn.Config(app, host=settings.web_host, port=settings.web_port, log_level="info", lifespan="on")
    server = uvicorn.Server(config)
    log.info("Web server started on %s:%s", settings.web_host, settings.web_port)
    await server.serve()


async def shutdown_resources(bot: Bot | None = None) -> None:
    """Graceful shutdown всех ресурсов."""
    log.info("Graceful shutdown...")

    if bot is not None:
        await delete_webhook(bot)
        await bot.session.close()

    await close_redis()
    await close_spotify_client()
    await close_lastfm_client()

    # Даем время на завершение pending задач
    await asyncio.sleep(0.5)
    log.info("Shutdown complete")


async def main() -> None:
    await init_db()
    setup_logging()  # Alembic снёс хендлеры root-логгера — восстанавливаем
    init_sentry()  # no-op без SENTRY_DSN

    settings = get_settings()
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = create_dispatcher()

    # Регистрируем bot и dispatcher в web app для webhook handler
    set_webhook_bot(bot)
    set_webhook_dispatcher(dp)
    await setup_bot_meta(bot)

    try:
        if settings.use_webhook:
            # Webhook mode: webhook server + web server
            await asyncio.gather(
                run_webhook_mode(bot, dp),
                run_web_server(),
            )
        else:
            # Polling mode: polling + web server
            await asyncio.gather(
                run_polling(bot, dp),
                run_web_server(),
            )
    except asyncio.CancelledError:
        log.info("Main task cancelled")
    except Exception:
        log.exception("Fatal error")
        raise
    finally:
        await shutdown_resources(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Interrupted by user")
        sys.exit(0)