"""FastAPI-приложение (только OAuth callbacks + healthcheck)."""
from fastapi import FastAPI

from app.web.oauth import router as oauth_router


def create_web_app() -> FastAPI:
    app = FastAPI(title="PlayMyStation OAuth")
    app.include_router(oauth_router)

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    return app
