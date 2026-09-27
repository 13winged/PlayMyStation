"""YouTube Music: история прослушиваний через ytmusicapi (browser auth).

У YouTube Music нет realtime 'currently playing' в API,
поэтому берём последний трек из истории (`get_history`)
и помечаем is_playing=False — честный UX «последний трек», как у Last.fm.

Привязка: `/youtube <полные заголовки из браузера>` (browser auth по документации
ytmusicapi: music.youtube.com → DevTools → Network → фильтр `/browse` →
Copy Request Headers). Нужны в том числе `authorization: SAPISIDHASH...`,
`cookie:` (с `__Secure-3PAPISID` — признак входа в аккаунт) и
`x-goog-authuser:`. В БД храним готовый auth-JSON (вывод `ytmusicapi.setup`)
в зашифрованном виде. Живёт ~2 года, пока жива сессия в браузере.

Sync-библиотека ytmusicapi выполняется в asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile

from app.core.retry import YOUTUBE_CIRCUIT
from app.services.audio import MAX_TRACK_BYTES, fetch_audio_bytes
from app.services.base import BaseMusicService, TrackDTO
from app.services.youtube_oauth import (
    fetch_streaming_sync,
    is_oauth_json,
    server_oauth_credentials,
)

log = logging.getLogger("playmystation.youtube")

REQUIRED_HEADER_KEYS = frozenset({"authorization", "cookie", "x-goog-authuser"})

# Строка вида "Header-Name:" (двоеточие, пустое значение) — Firefox/Chrome
# при копировании иногда кладут значение на следующую строку. Склеиваем.
_SPLIT_HEADER_RE = re.compile(r"^[A-Za-z0-9-]+:$")


def normalize_headers_raw(headers_raw: str) -> str:
    """Склеить заголовки, чьё значение перенесено на следующую строку.

    Чистая функция: "authorization:" + "SAPISIDHASH ..." →
    "authorization: SAPISIDHASH ...". Строки вида "Name: value" не трогаем.
    """
    merged: list[str] = []
    for line in headers_raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if (
            merged
            and _SPLIT_HEADER_RE.fullmatch(merged[-1].strip())
            and ": " not in stripped
        ):
            merged[-1] = merged[-1].rstrip() + " " + stripped
        else:
            merged.append(line)
    return "\n".join(merged)

# В истории YT для видео вторым «артистом» часто прилетает счётчик
# просмотров ("29M views", "1,1 млн просмотров") — вычищаем.
_VIEWS_RE = re.compile(r"view|просмотр|stream|listen", re.IGNORECASE)
# Автогенерированные каналы вида "Joji - Topic" — режем суффикс.
_TOPIC_RE = re.compile(r"\s+-\s+topic$", re.IGNORECASE)


def validate_auth_json(auth_json: str) -> None:
    """Проверить готовый auth-JSON до сохранения.

    Бросает ValueError с человекочитаемой причиной:
    - не JSON / нет нужных заголовков;
    - в cookie нет `__Secure-3PAPISID` — заголовки скопированы
      из незалогиненной (гостевой) сессии, история не откроется.
    """
    try:
        data = json.loads(auth_json)
    except (json.JSONDecodeError, TypeError) as e:
        raise ValueError("not JSON") from e
    if not isinstance(data, dict):
        raise TypeError("not JSON")
    lowered = {str(k).lower(): v for k, v in data.items()}
    missing = sorted(REQUIRED_HEADER_KEYS - set(lowered))
    if missing:
        raise ValueError(f"missing headers: {', '.join(missing)}")
    authorization = str(lowered.get("authorization") or "")
    if "SAPISIDHASH" not in authorization:
        # Зеркалим детект BROWSER в ytmusicapi: без SAPISIDHASH нас
        # классифицируют как OAuth и упадут с YTMusicUserError.
        raise ValueError("bad authorization: no SAPISIDHASH (copy the full line)")
    cookie = str(lowered.get("cookie") or "")
    if "__Secure-3PAPISID" not in cookie:
        raise ValueError("not logged in: no __Secure-3PAPISID in cookie")


def build_auth_json(headers_raw: str) -> str:
    """Превратить скопированные заголовки браузера в auth-JSON.

    Синхронная: вызывает `ytmusicapi.setup(headers_raw=...)`, затем
    валидирует результат через `validate_auth_json`.
    Бросает ValueError, если заголовки неполные/гостевые.
    """
    from ytmusicapi import setup  # lazy import — тяжёлая зависимость

    try:
        auth_json = setup(headers_raw=normalize_headers_raw(headers_raw))
    except Exception as e:
        raise ValueError(f"bad headers: {e}") from e
    validate_auth_json(auth_json)
    return auth_json


def _auth_dict(auth_json: str) -> dict:
    data = json.loads(auth_json)
    if not isinstance(data, dict) or "cookie" not in {k.lower() for k in data}:
        raise ValueError("auth JSON без cookie")
    return data


def _fetch_history_sync(auth_json: str) -> list:
    from ytmusicapi import YTMusic  # lazy import — тяжёлая зависимость

    if is_oauth_json(auth_json):
        creds = server_oauth_credentials()
        if creds is None:
            raise ValueError("YouTube OAuth is not configured on the server")
        yt = YTMusic(auth=json.loads(auth_json), oauth_credentials=creds)
    else:
        yt = YTMusic(auth=_auth_dict(auth_json))
    history = yt.get_history()
    return history if isinstance(history, list) else []


async def check_auth(auth_json: str) -> bool:
    """Проверить auth-JSON: True если запрос истории прошёл (даже пустой)."""
    try:
        await asyncio.to_thread(_fetch_history_sync, auth_json)
    except Exception:
        # Логируем только ИМЕНА ключей (без значений — там секреты).
        try:
            keys = sorted(str(k) for k in json.loads(auth_json))
        except (json.JSONDecodeError, TypeError, AttributeError):
            keys = []
        log.warning("YouTube auth check failed (keys=%s)", keys, exc_info=True)
        return False
    return True


def _video_meta_sync(video_id: str) -> dict | None:
    """Метаданные публичного видео без авторизации. Синхронная."""
    from ytmusicapi import YTMusic  # lazy import — тяжёлая зависимость

    try:
        song = YTMusic().get_song(video_id)
    except Exception:  # noqa: BLE001 — best-effort
        return None
    details = song.get("videoDetails") if isinstance(song, dict) else None
    if not isinstance(details, dict):
        return None
    return details


async def youtube_video_meta(video_id: str) -> TrackDTO | None:
    """TrackDTO из публичного YouTube-видео (для докачки по ссылке)."""
    details = await asyncio.to_thread(_video_meta_sync, video_id)
    if not details:
        return None
    title = details.get("title") or "Unknown title"
    artist = details.get("author") or "Unknown artist"
    thumbs = details.get("thumbnail") or {}
    cover = None
    if isinstance(thumbs, dict):
        items = thumbs.get("thumbnails") or []
        if items and isinstance(items[-1], dict):
            cover = items[-1].get("url")
    duration_ms = None
    length = details.get("lengthSeconds")
    try:
        duration_ms = int(length) * 1000 if length is not None else None
    except (TypeError, ValueError):
        duration_ms = None
    return TrackDTO(
        title=str(title),
        artist=str(artist),
        duration_ms=duration_ms,
        is_playing=False,
        cover_url=cover,
        track_url=f"https://music.youtube.com/watch?v={video_id}",
        provider="youtube",
        track_id=video_id,
    )


class YouTubeAuthExpired(Exception):
    """Куки привязки протухли (Google их ротирует) — нужна перепривязка."""

    def __init__(self, video_id: str) -> None:
        super().__init__(video_id)
        self.video_id = video_id


class _YtDlpLogger:
    """Проброс ошибок yt-dlp в наш лог (иначе фейлы молчаливые)."""

    def __init__(self, video_id: str) -> None:
        self._video_id = video_id
        self.cookies_invalid = False

    def debug(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        log.info("yt-dlp [%s]: %s", self._video_id, msg)

    def error(self, msg: str) -> None:
        if "cookies are no longer valid" in msg.lower():
            self.cookies_invalid = True
        log.warning("yt-dlp [%s] ERROR: %s", self._video_id, msg)


def player_clients(has_cookie: bool) -> list[str]:
    """Player-клиенты YouTube под ситуацию.

    С куками: tv + web (android скипается самим yt-dlp при куках).
    Без кук: android первым — обходит 'Sign in to confirm you're not a bot'.
    """
    return ["tv", "web"] if has_cookie else ["android", "web"]


def _download_youtube_sync(
    video_id: str, cookie_header: str | None = None
) -> tuple[bytes, str] | None:
    """Скачать аудио через yt-dlp во временную директорию. Синхронная.

    cookie_header — сырая строка `Cookie` из browser-auth: YouTube банит
    датацентровые IP («Sign in to confirm you're not a bot»), с куками
    юзера скачивание идёт от его имени и блок снимается.
    """
    from yt_dlp import YoutubeDL  # lazy import — тяжёлая зависимость

    url = f"https://music.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory(prefix="pms-yt-") as workdir:
        logger = _YtDlpLogger(video_id)
        opts: dict = {
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": os.path.join(workdir, "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "max_filesize": MAX_TRACK_BYTES,
            "logger": logger,
            # Node есть в образе, но yt-dlp по умолчанию включает только deno.
            "js_runtimes": {"node": {"path": None}},
            "extractor_args": {"youtube": {"player_client": player_clients(bool(cookie_header))}},
        }
        if cookie_header:
            cookie_file = os.path.join(workdir, "cookies.txt")
            with open(cookie_file, "w", encoding="utf-8") as f:
                f.write(cookie_header_to_netscape(cookie_header))
            opts["cookiefile"] = cookie_file
        try:
            with YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception:
            if logger.cookies_invalid:
                raise YouTubeAuthExpired(video_id)
            raise
        for name in os.listdir(workdir):
            if name.startswith(video_id):
                ext = name.rsplit(".", 1)[-1] if "." in name else "m4a"
                with open(os.path.join(workdir, name), "rb") as f:
                    data = f.read()
                if not data or len(data) > MAX_TRACK_BYTES:
                    return None
                return data, ext
    return None


def extract_cookie(auth_json: str) -> str | None:
    """Достать сырую Cookie-строку из сохранённого auth-JSON. None если нет."""
    try:
        data = json.loads(auth_json)
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None
    if not isinstance(data, dict):
        return None
    for key, value in data.items():
        if str(key).lower() == "cookie" and isinstance(value, str) and value.strip():
            return value.strip()
    return None


def cookie_header_to_netscape(cookie_header: str) -> str:
    """Cookie-строка браузера → Netscape cookie file для yt-dlp."""
    import time as _time

    expiry = int(_time.time()) + 365 * 24 * 3600
    lines = ["# Netscape HTTP Cookie File"]
    for part in cookie_header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        name, value = name.strip(), value.strip()
        if not name or not value:
            continue
        secure = "TRUE" if name.startswith("__Secure-") else "FALSE"
        lines.append(f".youtube.com\tTRUE\t/\t{secure}\t{expiry}\t{name}\t{value}")
    return "\n".join(lines) + "\n"


def parse_duration_seconds(value: object) -> int | None:
    """'4:38' / '1:02:03' / секунды → секунды. None если не разобрать."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    if isinstance(value, str):
        try:
            total = 0
            for part in value.strip().split(":"):
                total = total * 60 + int(part)
        except ValueError:
            return None
        return total or None
    return None


def _search_candidates_sync(query: str, limit: int = 5) -> list[dict]:
    """Поиск песен на YouTube Music без авторизации. Синхронная."""
    from ytmusicapi import YTMusic  # lazy import — тяжёлая зависимость

    yt = YTMusic()
    results = yt.search(query, filter="songs", limit=limit) or []
    candidates = []
    for r in results:
        if not isinstance(r, dict):
            continue
        video_id = r.get("videoId")
        if not video_id:
            continue
        duration = parse_duration_seconds(r.get("duration_seconds", r.get("duration")))
        candidates.append(
            {"videoId": video_id, "duration_seconds": duration, "title": r.get("title")}
        )
    return candidates


def pick_match(
    candidates: list[dict], expected_ms: int | None, tolerance_s: int = 7
) -> str | None:
    """Выбрать videoId по близости длительности.

    Без expected — первый кандидат. Вне допуска — None (лучше превью,
    чем чужой трек: кавер/live с тем же названием).
    """
    if not candidates:
        return None
    if not expected_ms:
        return str(candidates[0]["videoId"])
    expected = expected_ms / 1000
    ranked = sorted(
        candidates,
        key=lambda c: abs((c.get("duration_seconds") or expected) - expected),
    )
    best = ranked[0]
    best_dur = best.get("duration_seconds")
    if best_dur is None:
        return str(best["videoId"])
    if abs(best_dur - expected) <= tolerance_s:
        return str(best["videoId"])
    log.info("no duration match for %.0fs among %d candidates", expected, len(candidates))
    return None


async def _download_via_streaming(auth_json: str, video_id: str) -> tuple[bytes, str] | None:
    """Скачать аудио прямым потоком через OAuth-сессию юзера (без yt-dlp)."""
    try:
        picked = await asyncio.to_thread(fetch_streaming_sync, auth_json, video_id)
    except Exception:  # noqa: BLE001 — best-effort докачка
        await YOUTUBE_CIRCUIT.record_failure()
        return None
    if picked is None:
        return None
    url, ext = picked
    data = await fetch_audio_bytes(url, max_bytes=MAX_TRACK_BYTES)
    if not data:
        return None
    await YOUTUBE_CIRCUIT.record_success()
    return data, ext


async def download_by_query(
    query: str, duration_ms: int | None = None, youtube_auth: str | None = None
) -> tuple[bytes, str] | None:
    """Найти трек на YouTube Music по 'Artist - Title' и скачать аудио.

    Схема как у Spotisaver: метаданные → поиск совпадения → скачивание.
    Поиск не требует авторизации. Скачивание: OAuth-поток по youtube_auth,
    иначе yt-dlp с куками из него, иначе анонимно (возможен бан по IP).
    """
    try:
        candidates = await asyncio.to_thread(_search_candidates_sync, query)
    except Exception:  # noqa: BLE001 — best-effort
        await YOUTUBE_CIRCUIT.record_failure()
        return None
    video_id = pick_match(candidates, duration_ms)
    if not video_id:
        return None
    if youtube_auth and is_oauth_json(youtube_auth):
        return await _download_via_streaming(youtube_auth, video_id)
    cookie = extract_cookie(youtube_auth) if youtube_auth else None
    try:
        async with asyncio.timeout(110):
            result = await asyncio.to_thread(_download_youtube_sync, video_id, cookie)
    except YouTubeAuthExpired:
        await YOUTUBE_CIRCUIT.record_failure()
        raise
    except (TimeoutError, Exception):  # noqa: BLE001 — best-effort докачка
        await YOUTUBE_CIRCUIT.record_failure()
        return None
    if result is None:
        return None
    await YOUTUBE_CIRCUIT.record_success()
    return result


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
            _TOPIC_RE.sub("", a.get("name", ""))
            for a in raw_artists
            if isinstance(a, dict) and a.get("name") and not _VIEWS_RE.search(a["name"])
        ]
        artist = ", ".join(n for n in names if n) or "Unknown artist"

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
            track_id=video_id,
        )

    async def download_track(
        self, track: TrackDTO, youtube_auth: str | None = None
    ) -> tuple[bytes, str] | None:
        """Скачать полный трек.

        OAuth-привязка → прямой аудиопоток через сессию юзера (без yt-dlp).
        Browser-привязка → yt-dlp с куками юзера (иначе бан серверного IP).
        """
        if not track.track_id:
            return None
        if is_oauth_json(self._auth_json):
            return await _download_via_streaming(self._auth_json, track.track_id)
        cookie = extract_cookie(self._auth_json)
        try:
            async with asyncio.timeout(110):
                data_ext = await asyncio.to_thread(
                    _download_youtube_sync, track.track_id, cookie
                )
        except YouTubeAuthExpired:
            await YOUTUBE_CIRCUIT.record_failure()
            raise
        except (TimeoutError, Exception):  # noqa: BLE001 — best-effort докачка
            await YOUTUBE_CIRCUIT.record_failure()
            return None
        if data_ext is None:
            return None
        await YOUTUBE_CIRCUIT.record_success()
        return data_ext
