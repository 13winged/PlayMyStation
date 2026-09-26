"""Скачивание аудио для кнопки «⏬ Превью» и автодокачки в /now.

Честные ограничения и решения владельца — см. README «Скачивание треков в /now».
"""

from __future__ import annotations

import hashlib
import logging
import re

import httpx

from app.services.base import TrackDTO

log = logging.getLogger("playmystation.audio")

# Превью Spotify ~300–500 КБ; кап с запасом, чтобы не тащить мусор в память.
MAX_AUDIO_BYTES = 8 * 1024 * 1024
# Полные треки (Яндекс/YouTube): лимит Bot API — 50 МБ, берём с запасом ниже.
MAX_TRACK_BYTES = 45 * 1024 * 1024
DOWNLOAD_TIMEOUT = 20.0


def safe_filename(artist: str, title: str, ext: str = "mp3") -> str:
    """Безопасное имя файла из исполнителя и названия (для Telegram audio)."""
    parts = [p.strip() for p in (artist, title) if p.strip()]
    base = " - ".join(parts) or "track"
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).strip().rstrip(".")
    if len(base) > 60:
        base = base[:60].rstrip()
    return f"{base or 'track'}.{ext}"


def audio_cache_key(track: TrackDTO) -> str | None:
    """Стабильный ключ трека для кеша file_id.

    Приоритет точному ID (провайдер + track_id); иначе — хэш нормализованных
    метаданных (для Spotify/Last.fm, где аудио находится матчингом:
    один и тот же запрос даёт то же аудио).
    """
    if track.provider in ("youtube", "yandex", "spotify") and track.track_id:
        return f"audio:{track.provider}:{track.track_id}"
    if track.provider == "spotify" and track.preview_url:
        digest = hashlib.sha256(track.preview_url.encode()).hexdigest()[:32]
        return f"audio:spotify:preview:{digest}"
    supported = ("spotify", "lastfm", "youtube", "yandex")
    if track.provider in supported and track.artist and track.title:
        parts = [
            track.artist.strip().lower(),
            track.title.strip().lower(),
            str(track.duration_ms),
        ]
        norm = re.sub(r"\s+", " ", "|".join(parts))
        digest = hashlib.sha256(norm.encode()).hexdigest()[:32]
        return f"audio:{track.provider}:meta:{digest}"
    return None


async def fetch_audio_bytes(url: str, max_bytes: int = MAX_AUDIO_BYTES) -> bytes | None:
    """Скачать аудио по прямой ссылке. Вернёт None при любой проблеме."""
    try:
        async with (
            httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as client,
            client.stream("GET", url) as resp,
        ):
            if resp.status_code != 200:
                return None
            length = resp.headers.get("Content-Length")
            if length is not None:
                try:
                    if int(length) > max_bytes:
                        log.warning("Audio too large (%s bytes), skip %s", length, url)
                        return None
                except ValueError:
                    pass
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes(64 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    log.warning("Audio exceeded cap while streaming, skip %s", url)
                    return None
                chunks.append(chunk)
            data = b"".join(chunks)
            return data or None
    except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError, httpx.HTTPError):
        return None
    except Exception:
        log.exception("Unexpected error downloading audio")
        return None
