"""Кросс-платформенный матчинг «этот же трек на …» без song.link.

song.link стал отвечать 401 без API-ключа, поэтому ищем нативными поисками:
- Spotify — app-токен (client credentials, серверные ключи, без юзера);
- Yandex — поиск по токену юзера;
- YouTube — открытый поиск ytmusicapi (без авторизации).
Совпадение проверяем по длительности (±7 c), мэппинги кешируем в Redis на 7 дней.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time

import httpx

from app.core.retry import CROSSLINK_CIRCUIT
from app.services.base import TrackDTO

log = logging.getLogger("playmystation.crosslink")

TOLERANCE_S = 7
SEARCH_TIMEOUT = 10.0

# Spotify client-credentials токен (общий для всех поисков, кеш в памяти).
_spotify_token: str | None = None
_spotify_expiry: float = 0.0
_spotify_client_id_used: str | None = None
_spotify_lock = asyncio.Lock()


def build_query(track: TrackDTO) -> str | None:
    """'Artist - Title' для поиска. None если метаданных нет."""
    if not track.artist or track.artist == "Unknown artist" or not track.title:
        return None
    return f"{track.artist} - {track.title}"


def pick_by_duration(
    candidates: list[tuple[str, int | None]],
    expected_ms: int | None,
    tolerance_s: int = TOLERANCE_S,
) -> str | None:
    """Выбрать URL по близости длительности. Без expected — первый."""
    if not candidates:
        return None
    if not expected_ms:
        return candidates[0][0]
    expected = expected_ms / 1000
    ranked = sorted(
        candidates, key=lambda c: abs((c[1] / 1000 if c[1] is not None else expected) - expected)
    )
    url, duration_ms = ranked[0]
    if duration_ms is None:
        return url
    if abs(duration_ms / 1000 - expected) <= tolerance_s:
        return url
    log.info("crosslink: no duration match for %.0fs among %d", expected, len(candidates))
    return None


async def _spotify_app_token() -> str | None:
    """App-токен Spotify (client credentials). None если ключей нет."""
    global _spotify_token, _spotify_expiry, _spotify_client_id_used
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.spotify_client_id or not settings.spotify_client_secret:
        return None
    async with _spotify_lock:
        # Ключи сменились (ротация) — старый токен невалиден, берём заново.
        if settings.spotify_client_id != _spotify_client_id_used:
            _spotify_token, _spotify_expiry = None, 0.0
        if _spotify_token and time.time() < _spotify_expiry - 60:
            return _spotify_token
        basic = base64.b64encode(
            f"{settings.spotify_client_id}:{settings.spotify_client_secret}".encode()
        ).decode()
        try:
            async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
                resp = await client.post(
                    "https://accounts.spotify.com/api/token",
                    headers={"Authorization": f"Basic {basic}"},
                    data={"grant_type": "client_credentials"},
                )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError):
            return None
        if resp.status_code != 200:
            return None
        data = resp.json()
        _spotify_token = data.get("access_token")
        _spotify_expiry = time.time() + int(data.get("expires_in", 3600))
        _spotify_client_id_used = settings.spotify_client_id
        return _spotify_token


def _spotify_search_sync(token: str, query: str) -> list[tuple[str, int | None]]:
    with httpx.Client(timeout=SEARCH_TIMEOUT) as client:
        resp = client.get(
            "https://api.spotify.com/v1/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": query, "type": "track", "limit": 5},
        )
    if resp.status_code != 200:
        return []
    items = (resp.json().get("tracks") or {}).get("items") or []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = (item.get("external_urls") or {}).get("spotify")
        if url:
            out.append((str(url), item.get("duration_ms")))
    return out


def _yandex_search_sync(user_token: str, query: str) -> list[tuple[str, int | None]]:
    from yandex_music import Client  # lazy import — тяжёлая зависимость

    client = Client(user_token).init()
    result = client.search(query)
    tracks = (result.tracks.results if result and result.tracks else []) or []
    out = []
    for t in tracks[:5]:
        albums = getattr(t, "albums", None) or []
        if not albums:
            continue
        url = f"https://music.yandex.ru/album/{albums[0].id}/track/{t.id}"
        out.append((url, getattr(t, "duration_ms", None)))
    return out


async def match_same_track(
    track: TrackDTO, yandex_token: str | None = None
) -> dict[str, str]:
    """Найти тот же трек на других платформах (кроме своей). {} если нет."""
    from app.core.redis import get_cached_platform_links, set_cached_platform_links

    query = build_query(track)
    if query is None:
        return {}
    cache_key = track.track_url or f"manual:{track.provider}:{track.artist}|{track.title}"
    cached = await get_cached_platform_links(cache_key)
    if cached:
        return {p: u for p, u in cached.items() if p != track.provider}

    if CROSSLINK_CIRCUIT.is_open:
        return {}

    async def _spotify() -> list[tuple[str, int | None]]:
        token = await _spotify_app_token()
        if token is None:
            return []
        try:
            return await asyncio.to_thread(_spotify_search_sync, token, query)
        except Exception:  # noqa: BLE001 — один поиск не роняет матчинг
            return []

    async def _yandex() -> list[tuple[str, int | None]]:
        if not yandex_token:
            return []
        try:
            return await asyncio.to_thread(_yandex_search_sync, yandex_token, query)
        except Exception:  # noqa: BLE001 — см. выше
            return []

    async def _youtube() -> list[tuple[str, int | None]]:
        from app.services.youtube import _search_candidates_sync

        try:
            cands = await asyncio.to_thread(_search_candidates_sync, query)
        except Exception:  # noqa: BLE001 — см. выше
            return []
        out = []
        for c in cands:
            vid = c.get("videoId")
            if not vid:
                continue
            dur = c.get("duration_seconds")
            out.append(
                (f"https://music.youtube.com/watch?v={vid}", dur * 1000 if dur else None)
            )
        return out

    jobs: dict[str, object] = {}
    if track.provider != "spotify":
        jobs["spotify"] = _spotify()
    if track.provider != "yandex":
        jobs["yandex"] = _yandex()
    if track.provider != "youtube":
        jobs["youtube"] = _youtube()
    if not jobs:
        return {}

    links: dict[str, str] = {}
    try:
        results = await asyncio.gather(*jobs.values())
    except Exception:  # noqa: BLE001 — матчинг best-effort
        await CROSSLINK_CIRCUIT.record_failure()
        return {}
    for platform, cands in zip(jobs, results, strict=True):
        url = pick_by_duration(cands, track.duration_ms)  # type: ignore[arg-type]
        if url:
            links[platform] = url
    if links:
        await CROSSLINK_CIRCUIT.record_success()
        await set_cached_platform_links(cache_key, links)
    return links


def spotify_meta_to_dto(data: dict, page_url: str) -> TrackDTO:
    """Метаданные GET /v1/tracks/{id} (app-токен) → TrackDTO для докачки по ссылке."""
    artists = ", ".join(a.get("name", "") for a in data.get("artists", [])) or "Unknown artist"
    images = (data.get("album") or {}).get("images") or []
    return TrackDTO(
        title=data.get("name", "Unknown title"),
        artist=artists,
        album=(data.get("album") or {}).get("name"),
        duration_ms=data.get("duration_ms"),
        is_playing=False,
        cover_url=images[0]["url"] if images else None,
        track_url=page_url,
        provider="spotify",
        preview_url=data.get("preview_url"),
        track_id=data.get("id"),
    )


async def spotify_track_meta(track_id: str) -> TrackDTO | None:
    """Метаданные публичного Spotify-трека по ID (app-токен, без юзера)."""
    token = await _spotify_app_token()
    if token is None:
        return None
    try:
        async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
            resp = await client.get(
                f"https://api.spotify.com/v1/tracks/{track_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
    except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError):
        return None
    if resp.status_code != 200:
        return None
    data = resp.json()
    if not isinstance(data, dict):
        return None
    return spotify_meta_to_dto(data, f"https://open.spotify.com/track/{track_id}")
