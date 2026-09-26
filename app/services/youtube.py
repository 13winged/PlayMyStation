"""YouTube Music: история прослушиваний через ytmusicapi (browser auth).

У YouTube Music нет realtime 'currently playing' в API,
поэтому берём последний трек из истории (`get_history`)
и помечаем is_playing=False — честный UX «последний трек», как у Last.fm.

Привязка: `/youtube <заголовки из браузера>` (browser auth по документации
ytmusicapi: music.youtube.com → DevTools → Network → фильтр `/browse` →
copy request headers). Достаточно строк `cookie:` и `x-goog-authuser:`.
В БД храним готовый auth-JSON (вывод `ytmusicapi.setup`) в зашифрованном
виде. Живёт ~2 года, пока жива сессия в браузере.

Sync-библиотека ytmusicapi выполняется в asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
import json
import logging

from app.core.retry import YOUTUBE_CIRCUIT
from app.services.base import BaseMusicService, TrackDTO

log = logging.getLogger("playmystation.youtube")


def build_auth_json(headers_raw: str) -> str:
    """Превратить скопированные заголовки браузера в auth-JSON.

    Синхронная: вызывает `ytmusicapi.setup(headers_raw=...)`.
    Нужны ПОЛНЫЕ заголовки запроса /browse (включая `authorization: SAPISIDHASH...`,
    `cookie:` и `x-goog-authuser:`) — иначе YTMusic не признает browser-auth.
    Бросает ValueError, если заголовки неполные/не parse'ятся.
    """
    import json as _json

    from ytmusicapi import setup  # lazy import — тяжёлая зависимость

    try:
        auth_json = setup(headers_raw=headers_raw)
    except Exception as e:
        raise ValueError(f"bad headers: {e}") from e
    keys = {k.lower() for k in _json.loads(auth_json)}
    missing = {"authorization", "cookie", "x-goog-authuser"} - keys
    if missing:
        raise ValueError(f"missing headers: {', '.join(sorted(missing))}")
    return auth_json


def _auth_dict(auth_json: str) -> dict:
    data = json.loads(auth_json)
    if not isinstance(data, dict) or "cookie" not in {k.lower() for k in data}:
        raise ValueError("auth JSON без cookie")
    return data


def _fetch_history_sync(auth_json: str) -> list:
    from ytmusicapi import YTMusic  # lazy import — тяжёлая зависимость

    yt = YTMusic(auth=_auth_dict(auth_json))
    history = yt.get_history()
    return history if isinstance(history, list) else []


async def check_auth(auth_json: str) -> bool:
    """Проверить auth-JSON: True если запрос истории прошёл (даже пустой)."""
    try:
        await asyncio.to_thread(_fetch_history_sync, auth_json)
    except Exception:
        log.warning("YouTube auth check failed", exc_info=True)
        return False
    return True


class YouTubeMusicService(BaseMusicService):
    provider = "youtube"

    def __init__(self, auth_json: str) -> None:
        self._auth_json = auth_json

    async def get_currently_playing(self) -> TrackDTO | None:
        if YOUTUBE_CIRCUIT.is_open:
            return None  # сервис недавно сыпал ошибками — не дёргаем API
        try:
            history = await asyncio.to_thread(_fetch_history_sync, self._auth_json)
        except Exception:  # noqa: BLE001 — API нестабилен/кука протухла
            await YOUTUBE_CIRCUIT.record_failure()
            return None
        if not history:
            return None  # пустая история — штатно, не ошибка сервиса
        await YOUTUBE_CIRCUIT.record_success()
        first = history[0] if isinstance(history[0], dict) else {}
        return self._to_dto(first)

    @staticmethod
    def _to_dto(item: dict) -> TrackDTO:
        title = item.get("title") or "Unknown title"

        raw_artists = item.get("artists")
        if raw_artists is None:
            raw_artists = item.get("artist") or []
        if isinstance(raw_artists, dict):
            raw_artists = [raw_artists]
        names = [
            a.get("name", "")
            for a in raw_artists
            if isinstance(a, dict) and a.get("name")
        ]
        artist = ", ".join(names) or "Unknown artist"

        album = item.get("album")
        if isinstance(album, dict):
            album_name = album.get("name")
        elif isinstance(album, str):
            album_name = album
        else:
            album_name = None

        duration_ms: int | None = None
        ds = item.get("duration_seconds")
        if isinstance(ds, (int, float)) and ds > 0:
            duration_ms = int(ds * 1000)

        cover = None
        thumbs = item.get("thumbnails") or []
        if isinstance(thumbs, list) and thumbs and isinstance(thumbs[-1], dict):
            cover = thumbs[-1].get("url")

        video_id = item.get("videoId")
        track_url = f"https://music.youtube.com/watch?v={video_id}" if video_id else None

        return TrackDTO(
            title=title,
            artist=artist,
            album=album_name,
            duration_ms=duration_ms,
            progress_ms=None,  # история прогресс не отдаёт
            is_playing=False,  # realtime нет — всегда «последний трек»
            cover_url=cover,
            track_url=track_url,
            provider="youtube",
            preview_url=None,  # легального превью у YT Music нет
        )
