"""Spotify: OAuth2 + /me/player/currently-playing с авто-рефрешем токена, ретраями и circuit-breaker."""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import logging
from collections.abc import Awaitable, Callable

import httpx

from app.core.config import get_settings
from app.core.retry import SPOTIFY_CIRCUIT, create_retry_transport
from app.services.audio import fetch_audio_bytes
from app.services.base import BaseMusicService, TrackDTO
from app.services.youtube import download_by_query

log = logging.getLogger("playmystation.spotify")

TOKEN_URL = "https://accounts.spotify.com/api/token"
NOW_PLAYING_URL = "https://api.spotify.com/v1/me/player/currently-playing"
RECENTLY_PLAYED_URL = "https://api.spotify.com/v1/me/player/recently-played"

TokenSaver = Callable[[str, str | None, dt.datetime | None], Awaitable[None]]

# Shared client with retry transport
_spotify_client: httpx.AsyncClient | None = None
_spotify_client_lock = asyncio.Lock()


async def _get_spotify_client() -> httpx.AsyncClient:
    global _spotify_client
    async with _spotify_client_lock:
        if _spotify_client is None or _spotify_client.is_closed:
            _spotify_client = httpx.AsyncClient(
                timeout=15.0,
                transport=create_retry_transport(
                    max_retries=3,
                    base_delay=0.5,
                    max_delay=10.0,
                    retry_on_status=(429, 500, 502, 503, 504),
                ),
            )
        return _spotify_client


async def close_spotify_client() -> None:
    global _spotify_client
    async with _spotify_client_lock:
        if _spotify_client is not None and not _spotify_client.is_closed:
            await _spotify_client.aclose()
            _spotify_client = None


def build_authorize_url(
    state: str,
    scopes: str = (
        "user-read-currently-playing user-read-playback-state user-read-recently-played"
    ),
) -> str:
    s = get_settings()
    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": s.spotify_client_id,
        "scope": scopes,
        "redirect_uri": s.spotify_redirect_uri,
        "state": state,
    }
    return "https://accounts.spotify.com/authorize?" + urlencode(params)


class SpotifyService(BaseMusicService):
    provider = "spotify"

    def __init__(
        self,
        access_token: str,
        refresh_token: str | None = None,
        expires_at: dt.datetime | None = None,
        on_tokens_refreshed: TokenSaver | None = None,
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
            basic = base64.b64encode(
                f"{s.spotify_client_id}:{s.spotify_client_secret}".encode()
            ).decode()

            client = await _get_spotify_client()
            try:
                resp = await SPOTIFY_CIRCUIT.call(
                    client.post,
                    TOKEN_URL,
                    headers={"Authorization": f"Basic {basic}"},
                    data={"grant_type": "refresh_token", "refresh_token": self._refresh_token},
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

        client = await _get_spotify_client()

        async def _do_request() -> httpx.Response:
            return await client.get(
                NOW_PLAYING_URL,
                headers={"Authorization": f"Bearer {self._access_token}"},
            )

        try:
            resp = await SPOTIFY_CIRCUIT.call(_do_request)
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 401 and self._refresh_token and await self._refresh():
                return await self.get_currently_playing()
            # Circuit breaker open или другая ошибка
            log.info("currently-playing request failed: %s", e)
            return None

        if resp.status_code == 204:
            log.info("currently-playing: 204 No Content, trying recently-played")
            return await self._get_recently_played()
        if resp.status_code == 401 and self._refresh_token:
            log.info("currently-playing: 401, trying token refresh")
            if await self._refresh():
                return await self.get_currently_playing()
            log.warning("currently-playing: 401 and refresh failed")
            return None
        if resp.status_code == 403:
            # Free-аккаунты без Premium: Spotify закрывает realtime player API
            # (reason=PREMIUM_REQUIRED). Падаем назад на recently-played.
            try:
                body = resp.text[:200]
            except Exception:  # noqa: BLE001
                body = "<unreadable>"
            log.info("currently-playing: 403 Forbidden (%s), trying recently-played", body)
            return await self._get_recently_played()
        if resp.status_code != 200:
            log.info("currently-playing: unexpected status %s", resp.status_code)
            return None

        data = resp.json()
        item = data.get("item") or {}
        artists = ", ".join(a.get("name", "") for a in item.get("artists", [])) or "Unknown artist"
        images = (item.get("album") or {}).get("images") or []
        log.info(
            "currently-playing: '%s' — %s (is_playing=%s)",
            item.get("name"), artists, data.get("is_playing"),
        )
        return TrackDTO(
            title=item.get("name", "Unknown title"),
            artist=artists,
            album=(item.get("album") or {}).get("name"),
            duration_ms=item.get("duration_ms"),
            progress_ms=data.get("progress_ms"),
            is_playing=bool(data.get("is_playing", False)),
            cover_url=images[0]["url"] if images else None,
            track_url=(item.get("external_urls") or {}).get("spotify"),
            provider="spotify",
            preview_url=item.get("preview_url"),  # 30-секундное превью (может быть None)
        )

    async def _get_recently_played(self) -> TrackDTO | None:
        """Фолбэк для случаев, когда realtime player API недоступен.

        `recently-played` работает и на free-аккаунтах (нужен скоуп
        user-read-recently-played). Возвращает последний трек
        с is_playing=False — честный UX «последний трек», как у YouTube Music.
        """
        client = await _get_spotify_client()

        async def _do_request() -> httpx.Response:
            return await client.get(
                RECENTLY_PLAYED_URL,
                headers={"Authorization": f"Bearer {self._access_token}"},
                params={"limit": 1},
            )

        try:
            resp = await SPOTIFY_CIRCUIT.call(_do_request)
        except httpx.HTTPStatusError as e:
            log.info("recently-played request failed: %s", e)
            return None
        if resp.status_code != 200:
            log.info("recently-played: unexpected status %s", resp.status_code)
            return None
        data = resp.json()
        items = data.get("items") or []
        if not items:
            log.info("recently-played: empty history")
            return None
        item = (items[0].get("track") or {}) if isinstance(items[0], dict) else {}
        artists = ", ".join(a.get("name", "") for a in item.get("artists", [])) or "Unknown artist"
        images = (item.get("album") or {}).get("images") or []
        log.info("recently-played: '%s' — %s", item.get("name"), artists)
        return TrackDTO(
            title=item.get("name", "Unknown title"),
            artist=artists,
            album=(item.get("album") or {}).get("name"),
            duration_ms=item.get("duration_ms"),
            progress_ms=None,
            is_playing=False,
            cover_url=images[0]["url"] if images else None,
            track_url=(item.get("external_urls") or {}).get("spotify"),
            provider="spotify",
            preview_url=item.get("preview_url"),
        )

    async def download_track(self, track: TrackDTO) -> tuple[bytes, str] | None:
        """Полный трек через YouTube-матчинг, фолбэк — 30-сек preview.

        Схема как у Spotisaver: из Spotify берём только метаданные
        (название + исполнитель + длительность), аудио ищем на YouTube.
        Совпадение проверяем по длительности (±7 сек), иначе лучше
        превью, чем чужой трек с тем же названием.
        """
        if track.artist and track.artist != "Unknown artist":
            full = await download_by_query(
                f"{track.artist} - {track.title}", track.duration_ms
            )
            if full is not None:
                return full
        if not track.preview_url:
            return None
        data = await fetch_audio_bytes(track.preview_url)
        if not data:
            return None
        return data, "mp3"