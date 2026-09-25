"""FastAPI OAuth-callbacks для Spotify и SoundCloud.

state = telegram_id. После обмена code->token сохраняем интеграцию в БД.
"""

from __future__ import annotations

import datetime as dt

import httpx
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionFactory
from app.db import repositories as repo
from app.db.models import User

router = APIRouter(prefix="/oauth", tags=["oauth"])


@router.get("/spotify/callback")
async def spotify_callback(code: str = Query(), state: str = Query()) -> dict:
    settings = get_settings()
    telegram_id = int(state)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://accounts.spotify.com/api/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.spotify_redirect_uri,
            },
            auth=(settings.spotify_client_id, settings.spotify_client_secret),
        )
    if resp.status_code != 200:
        raise HTTPException(400, f"Spotify token exchange failed: {resp.text}")
    data = resp.json()
    expires_at = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=int(data.get("expires_in", 3600)))
    async with SessionFactory() as session:
        user = await repo.get_or_create_user(session, telegram_id)
        await repo.upsert_integration(
            session,
            user_id=user.id,
            provider="spotify",
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
        )
        await session.commit()
    return {
        "ok": True,
        "provider": "spotify",
        "detail": "Spotify подключён! Вернись в Telegram и нажми /now 🎵",
    }


@router.get("/soundcloud/callback")
async def soundcloud_callback(code: str = Query(), state: str = Query()) -> dict:
    settings = get_settings()
    if not settings.soundcloud_client_id:
        raise HTTPException(500, "SoundCloud OAuth не настроен")
    telegram_id = int(state)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://secure.soundcloud.com/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": settings.soundcloud_client_id,
                "client_secret": settings.soundcloud_client_secret,
                "redirect_uri": settings.soundcloud_redirect_uri,
                "code": code,
            },
        )
    if resp.status_code != 200:
        raise HTTPException(400, f"SoundCloud token exchange failed: {resp.text}")
    data = resp.json()
    async with SessionFactory() as session:
        res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = res.scalar_one_or_none() or await repo.get_or_create_user(session, telegram_id)
        await repo.upsert_integration(
            session,
            user_id=user.id,
            provider="soundcloud",
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
        )
        await session.commit()
    return {
        "ok": True,
        "provider": "soundcloud",
        "detail": "SoundCloud подключён! Вернись в Telegram 🎵",
    }
