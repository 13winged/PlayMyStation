"""Last.fm: недавние треки пользователя (скробблинг).

Зачем: Spotify без Premium закрывает realtime player API (403), а Last.fm
отдаёт `user.getrecenttracks` всем бесплатно — достаточно username, OAuth
не нужен. Юзер один раз связывает Spotify → Last.fm (скробблинг), бот читает
историю. Трек с флагом `@attr.nowplaying` считаем играющим прямо сейчас,
остальное — «последний трек» (честно, как у YouTube Music).
"""

from __future__ import annotations

import asyncio

import httpx

from app.core.config import get_settings
from app.core.retry import LASTFM_CIRCUIT, create_retry_transport
from app.services.base import BaseMusicService, TrackDTO
from app.services.youtube import download_by_query

API_URL = "https://ws.audioscrobbler.com/2.0/"

# Shared client with retry transport (exponential backoff, respects Retry-After)
_lastfm_client: httpx.AsyncClient | None = None
_lastfm_client_lock = asyncio.Lock()


async def _get_lastfm_client() -> httpx.AsyncClient:
    global _lastfm_client
    async with _lastfm_client_lock:
        if _lastfm_client is None or _lastfm_client.is_closed:
            _lastfm_client = httpx.AsyncClient(
                timeout=15.0,
                transport=create_retry_transport(
                    max_retries=3,
                    base_delay=0.5,
                    max_delay=10.0,
                    retry_on_status=(429, 500, 502, 503, 504),
                ),
            )
        return _lastfm_client


async def close_lastfm_client() -> None:
    global _lastfm_client
    async with _lastfm_client_lock:
        if _lastfm_client is not None and not _lastfm_client.is_closed:
            await _lastfm_client.aclose()
            _lastfm_client = None


class LastFmService(BaseMusicService):
    provider = "lastfm"

    def __init__(self, username: str) -> None:
        self._username = username

    async def get_currently_playing(self) -> TrackDTO | None:
        settings = get_settings()
        if not settings.lastfm_api_key:
            return None
        if LASTFM_CIRCUIT.is_open:
            return None  # сервис недавно сыпал ошибками — не дёргаем API
        client = await _get_lastfm_client()
        try:
            resp = await client.get(
                API_URL,
                params={
                    "method": "user.getrecenttracks",
                    "user": self._username,
                    "api_key": settings.lastfm_api_key,
                    "format": "json",
                    "limit": 1,
                },
            )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError):
            await LASTFM_CIRCUIT.record_failure()
            return None
        if resp.status_code != 200:
            if resp.status_code >= 500:
                await LASTFM_CIRCUIT.record_failure()
            return None
        data = resp.json()
        tracks = (data.get("recenttracks") or {}).get("track") or []
        if isinstance(tracks, dict):
            tracks = [tracks]  # один трек API отдаёт объектом, а не списком
        if not tracks:
            return None
        await LASTFM_CIRCUIT.record_success()
        return self._to_dto(tracks[0])

    @staticmethod
    def _to_dto(t: dict) -> TrackDTO:
        artist = (t.get("artist") or {}).get("#text", "Unknown artist") or "Unknown artist"
        album = (t.get("album") or {}).get("#text") or None
        images = [i.get("#text") for i in (t.get("image") or []) if i.get("#text")]
        is_playing = (t.get("@attr") or {}).get("nowplaying") == "true"
        return TrackDTO(
            title=t.get("name", "Unknown title"),
            artist=artist,
            album=album,
            duration_ms=None,  # Last.fm длительность не отдаёт
            progress_ms=None,
            is_playing=is_playing,
            cover_url=images[-1] if images else None,
            track_url=t.get("url"),
            provider="lastfm",
            preview_url=None,  # превью нет — только ссылка на трек
        )

    async def download_track(self, track: TrackDTO) -> tuple[bytes, str] | None:
        """Аудио через YouTube-матчинг по метаданным скроббла.

        Длительности Last.fm не отдаёт — берём первый результат поиска.
        Best-effort: mismatch возможен, фолбэка нет.
        """
        if not track.artist or track.artist == "Unknown artist":
            return None
        return await download_by_query(f"{track.artist} - {track.title}")
