"""SoundCloud: OAuth2 + история прослушиваний.

У SoundCloud нет realtime 'currently playing' в public API,
поэтому берём последний трек из /me/play-history (или /me/activities)
и помечаем is_playing=False c пометкой 'last played'.
Если в будущем появится realtime endpoint — заменить только этот класс.

Поддерживает авто-рефреш access_token через refresh_token (как Spotify).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections.abc import Awaitable, Callable

import httpx

from app.core.config import get_settings
from app.core.retry import SOUNDCLOUD_CIRCUIT, create_retry_transport
from app.services.base import BaseMusicService, TrackDTO

log = logging.getLogger("playmystation.soundcloud")

TOKEN_URL = "https://secure.soundcloud.com/oauth/token"

# Shared client with retry transport (exponential backoff, respects Retry-After)
_soundcloud_client: httpx.AsyncClient | None = None
_soundcloud_client_lock = asyncio.Lock()


async def _get_soundcloud_client() -> httpx.AsyncClient:
    global _soundcloud_client
    async with _soundcloud_client_lock:
        if _soundcloud_client is None or _soundcloud_client.is_closed:
            _soundcloud_client = httpx.AsyncClient(
                timeout=15.0,
                transport=create_retry_transport(
                    max_retries=3,
                    base_delay=0.5,
                    max_delay=10.0,
                    retry_on_status=(429, 500, 502, 503, 504),
                ),
            )
        return _soundcloud_client


async def close_soundcloud_client() -> None:
    global _soundcloud_client
    async with _soundcloud_client_lock:
        if _soundcloud_client is not None and not _soundcloud_client.is_closed:
            await _soundcloud_client.aclose()
            _soundcloud_client = None


def build_authorize_url(state: str) -> str:
    s = get_settings()
    from urllib.parse import urlencode

    params = {
        "client_id": s.soundcloud_client_id,
        "redirect_uri": s.soundcloud_redirect_uri,
        "response_type": "code",
        "state": state,
    }
    return "https://secure.soundcloud.com/authorize?" + urlencode(params)


class SoundCloudService(BaseMusicService):
    provider = "soundcloud"

    def __init__(
        self,
        access_token: str,
        refresh_token: str | None = None,
        expires_at: dt.datetime | None = None,
        on_tokens_refreshed: Callable[[str, str | None, dt.datetime | None], Awaitable[None]] | None = None,
    ) -> None:
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._expires_at = expires_at
        self._on_tokens_refreshed = on_tokens_refreshed
        self._refresh_lock = asyncio.Lock()

    async def _refresh(self) -> bool:
        if not self._refresh_token:
            return False

        async with self._refresh_lock:
            # Double-check после получения лока
            if not self._refresh_token:
                return False

            s = get_settings()
            client = await _get_soundcloud_client()
            try:
                resp = await SOUNDCLOUD_CIRCUIT.call(
                    client.post,
                    TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "client_id": s.soundcloud_client_id,
                        "client_secret": s.soundcloud_client_secret,
                        "refresh_token": self._refresh_token,
                    },
                )
            except httpx.HTTPStatusError as e:
                if e.response is not None and e.response.status_code == 400:
                    # Invalid grant - refresh token revoked/expired
                    return False
                raise

            if resp.status_code != 200:
                return False

            data = resp.json()
            self._access_token = data["access_token"]
            expires_in = int(data.get("expires_in", 3600))
            self._expires_at = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=expires_in)
            if "refresh_token" in data:
                self._refresh_token = data["refresh_token"]

            if self._on_tokens_refreshed:
                await self._on_tokens_refreshed(
                    self._access_token, self._refresh_token, self._expires_at
                )
            return True

    async def get_currently_playing(self) -> TrackDTO | None:
        # Проактивный рефреш за 60 секунд до истечения
        if self._expires_at and self._refresh_token:
            now = dt.datetime.now(dt.UTC)
            if (self._expires_at - now).total_seconds() < 60:
                await self._refresh()

        if SOUNDCLOUD_CIRCUIT.is_open:
            return None  # сервис недавно сыпал ошибками — не дёргаем API

        headers = {"Authorization": f"OAuth {self._access_token}"}
        client = await _get_soundcloud_client()
        try:
            # 1) пробуем play-history (новый API)
            resp = await client.get(
                "https://api.soundcloud.com/me/play-history",
                headers=headers,
                params={"limit": 1},
            )
            if resp.status_code == 401 and self._refresh_token and await self._refresh():
                return await self.get_currently_playing()
            if resp.status_code == 401:
                return None
            items: list = []
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("collection", []) if isinstance(data, dict) else []
            # 2) фолбэк: последние лайки как 'recently played'
            if not items:
                fav = await client.get(
                    "https://api.soundcloud.com/me/favorites",
                    headers=headers,
                    params={"limit": 1},
                )
                if fav.status_code == 401 and self._refresh_token and await self._refresh():
                    return await self.get_currently_playing()
                if fav.status_code == 200 and isinstance(fav.json(), list) and fav.json():
                    t = fav.json()[0]
                    await SOUNDCLOUD_CIRCUIT.record_success()
                    return self._to_dto(t, is_playing=False)
                if fav.status_code >= 500:
                    await SOUNDCLOUD_CIRCUIT.record_failure()
                return None
            raw = items[0].get("track", items[0])
            await SOUNDCLOUD_CIRCUIT.record_success()
            return self._to_dto(raw, is_playing=False)
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError):
            await SOUNDCLOUD_CIRCUIT.record_failure()
            return None

    @staticmethod
    def _to_dto(t: dict, is_playing: bool) -> TrackDTO:
        artwork = t.get("artwork_url")
        if artwork:
            artwork = artwork.replace("large", "t500x500")
        user = t.get("user") or {}
        # Скачивание разрешено только если автор включил downloadable —
        # иначе качать трек нельзя (ToS SoundCloud).
        preview_url = t.get("download_url") if t.get("downloadable") else None
        return TrackDTO(
            title=t.get("title", "Unknown title"),
            artist=user.get("username", "Unknown artist"),
            album=None,
            duration_ms=t.get("duration_milliseconds"),
            progress_ms=None,
            is_playing=is_playing,
            cover_url=artwork,
            track_url=t.get("permalink_url"),
            provider="soundcloud",
            preview_url=preview_url,
        )
