"""FastAPI-приложение (OAuth callbacks + healthcheck + webhook + metrics)."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.metrics import (
    http_request_duration_seconds,
    http_requests_total,
    render_metrics,
)
from app.web.oauth import router as oauth_router

log = logging.getLogger("playmystation.web")

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
    if settings.use_webhook and not settings.webhook_secret:
        raise RuntimeError("WEBHOOK_SECRET is required in webhook mode")
    app = FastAPI(title="PlayMyStation OAuth", lifespan=lifespan)
    app.include_router(oauth_router)

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path) or request.url.path
        duration = time.perf_counter() - start
        http_requests_total.labels(request.method, path, response.status_code).inc()
        http_request_duration_seconds.labels(request.method, path).observe(duration)
        return response

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.get("/metrics")
    async def metrics() -> Response:
        body, content_type = render_metrics()
        return Response(content=body, media_type=content_type)

    @app.get("/ready")
    async def ready() -> Response:
        """Readiness: PostgreSQL + Redis доступны. Иначе 503."""
        from sqlalchemy import text

        from app.core.db import SessionFactory
        from app.core.redis import get_redis

        checks: dict[str, bool] = {"postgres": False, "redis": False}
        try:
            async with asyncio.timeout(3):
                async with SessionFactory() as session:
                    await session.execute(text("SELECT 1"))
                checks["postgres"] = True
        except Exception:
            log.warning("readiness: postgres unavailable", exc_info=True)
        try:
            async with asyncio.timeout(3):
                await (await get_redis()).ping()
                checks["redis"] = True
        except Exception:
            log.warning("readiness: redis unavailable", exc_info=True)
        ok = all(checks.values())
        return JSONResponse(
            status_code=200 if ok else 503, content={"ok": ok, **checks}
        )

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
                log.exception("Error processing update")
                raise HTTPException(status_code=500, detail=f"Error processing update: {e}")
            return {"ok": True}

    return app