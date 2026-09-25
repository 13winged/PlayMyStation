"""FastAPI-приложение (OAuth callbacks + healthcheck + webhook)."""

from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request

from app.core.config import get_settings
from app.web.oauth import router as oauth_router

# Глобальные instances для webhook (устанавливаются в main.py)
_bot: Bot | None = None
_dispatcher: Dispatcher | None = None


def set_webhook_bot(bot: Bot) -> None:
    """Установить bot instance для webhook handler."""
    global _bot
    _bot = bot


def set_webhook_dispatcher(dp: Dispatcher) -> None:
    """Установить dispatcher instance для webhook handler."""
    global _dispatcher
    _dispatcher = dp


def get_webhook_bot() -> Bot | None:
    return _bot


def get_webhook_dispatcher() -> Dispatcher | None:
    return _dispatcher


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ничего не делаем здесь, webhook ставится в main.py
    yield
    # Shutdown: ничего не делаем здесь


def create_web_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="PlayMyStation OAuth", lifespan=lifespan)
    app.include_router(oauth_router)

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    # Webhook endpoint (только если настроен webhook_url)
    if settings.use_webhook:
        @app.post(settings.webhook_path)
        async def webhook(
            request: Request,
            x_telegram_bot_api_secret_token: str | None = Header(None, alias="X-Telegram-Bot-Api-Secret-Token"),
        ) -> dict:
            # Проверка секрета
            if settings.webhook_secret and x_telegram_bot_api_secret_token != settings.webhook_secret:
                raise HTTPException(status_code=403, detail="Invalid secret token")

            bot = get_webhook_bot()
            dp = get_webhook_dispatcher()
            if bot is None or dp is None:
                raise HTTPException(status_code=500, detail="Bot or dispatcher not initialized")

            # Парсим update и передаём в dispatcher
            data = await request.json()
            update = Update.model_validate(data, context={"bot": bot})
            try:
                await dp.feed_update(bot, update)
            except Exception as e:
                import logging
                logging.exception("Error processing update")
                raise HTTPException(status_code=500, detail=f"Error processing update: {e}")
            return {"ok": True}

    return app