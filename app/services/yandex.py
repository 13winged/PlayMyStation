"""Yandex Music: работа по OAuth-токену.

Стратегия (по приоритету):
1. Ynison — нативный протокол Яндекса: реальный текущий трек + прогресс
   и пауза. Ходит через локальный Go-прокси (`ynison-proxy/`).
2. Фолбэк — очередь (`queues_list`): первый трек очереди считаем активным.
   Прогресс недоступен.

Sync-библиотека yandex-music выполняется в asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.retry import YANDEX_CIRCUIT
from app.services.audio import MAX_TRACK_BYTES, fetch_audio_bytes
from app.services.base import BaseMusicService, TrackDTO
from app.services.ynison import Ynison, YnisonError

log = logging.getLogger("playmystation.yandex")


def make_yandex_client(oauth_token: str):
    """Client Яндекс Музыки; при заданном YANDEX_PROXY_URL — через прокси."""
    from yandex_music import Client  # lazy import — тяжёлая зависимость

    from app.core.config import get_settings

    proxy = get_settings().yandex_proxy_url or None
    if proxy:
        from yandex_music.utils.request import Request  # lazy import

        return Client(oauth_token, request=Request(proxy_url=proxy)).init()
    return Client(oauth_token).init()


class YandexMusicService(BaseMusicService):
    provider = "yandex"

    def __init__(self, oauth_token: str) -> None:
        self._token = oauth_token

    def _track_dto_from_full(self, full) -> TrackDTO:  # type: ignore[no-untyped-def]
        artists = ", ".join(a.name for a in full.artists) if full.artists else "Unknown artist"
        cover = None
        if full.cover_uri:
            cover = "https://" + full.cover_uri.replace("%%", "400x400")
        track_url = (
            f"https://music.yandex.ru/album/{full.albums[0].id}/track/{full.id}"
            if full.albums
            else None
        )
        return TrackDTO(
            title=full.title or "Unknown title",
            artist=artists,
            album=full.albums[0].title if full.albums else None,
            duration_ms=int(full.duration_ms) if full.duration_ms else None,
            progress_ms=None,  # прогресс — только из Ynison, ниже
            is_playing=True,
            cover_url=cover,
            track_url=track_url,
            provider="yandex",
            track_id=str(full.id),
        )

    def _fetch_track_sync(self, track_id: str) -> TrackDTO | None:
        client = make_yandex_client(self._token)
        tracks = client.tracks([track_id])
        if not tracks:
            return None
        return self._track_dto_from_full(tracks[0])

    async def fetch_track(self, track_ref: str) -> TrackDTO | None:
        """Метаданные трека по ID ('id' или 'id:albumId') для докачки по ссылке."""
        try:
            return await asyncio.to_thread(self._fetch_track_sync, track_ref)
        except Exception:  # noqa: BLE001 — best-effort
            return None

    def _fetch_queue_sync(self) -> TrackDTO | None:
        client = make_yandex_client(self._token)
        queues = client.queues_list()
        if not queues:
            return None
        last_q = queues[0]
        current_id = last_q.current_index
        if current_id is None or current_id < 0 or current_id >= len(last_q.tracks):
            return None
        qtrack = last_q.tracks[current_id]
        full = qtrack.fetch_track()
        return self._track_dto_from_full(full)

    async def _ynison_snapshot(self) -> TrackDTO | None:
        """Realtime через Ynison. None — пробовать фолбэк очереди."""
        try:
            snapshot = await Ynison(self._token).get_now_playing()
        except YnisonError as e:
            log.info("ynison unavailable: %s", type(e).__name__)
            return None
        except Exception:  # noqa: BLE001 — транспорт/gRPC, деградируем в фолбэк
            log.info("ynison transport error, fallback to queue")
            return None
        current = next((i for i in snapshot.items if i.currently_playing), None)
        if current is None:
            return None
        try:
            track = await asyncio.to_thread(self._fetch_track_sync, current.playable_id)
        except Exception:  # noqa: BLE001 — метаданные не получены, деградируем в фолбэк
            return None
        if track is None:
            return None
        # Накладываем realtime-статус из Ynison
        track.progress_ms = snapshot.progress_ms
        if snapshot.duration_ms:
            track.duration_ms = snapshot.duration_ms
        track.is_playing = not snapshot.paused
        # playable_id — тот ID, которым трек реально резолвится в API,
        # его же используем для докачки аудио.
        track.track_id = current.playable_id
        return track

    async def get_currently_playing(self) -> TrackDTO | None:
        if YANDEX_CIRCUIT.is_open:
            return None  # сервис недавно сыпал ошибками — не дёргаем API
        track = await self._ynison_snapshot()
        if track is None:
            try:
                track = await asyncio.to_thread(self._fetch_queue_sync)
            except Exception:  # noqa: BLE001 — API Яндекса нестабилен
                await YANDEX_CIRCUIT.record_failure()
                return None
        # Пустая очередь — штатная ситуация, а не ошибка сервиса.
        if track is not None:
            await YANDEX_CIRCUIT.record_success()
        return track

    async def download_track(self, track: TrackDTO, youtube_auth: str | None = None) -> tuple[bytes, str] | None:
        """Скачать полный трек через прямые ссылки (токен юзера, его подписка)."""
        if not track.track_id:
            log.info("yandex download: no track_id for '%s'", track.title)
            return None
        try:
            # Sync-вызовы yandex-music без таймаутов — капаем снаружи,
            # иначе зависший API вешает задачу до внешнего таймаута.
            link, ext = await asyncio.wait_for(
                asyncio.to_thread(self._direct_link_sync, track.track_id),
                timeout=30,
            )
        except TimeoutError:
            log.warning("yandex download: direct link timed out for id=%s", track.track_id)
            await YANDEX_CIRCUIT.record_failure()
            return None
        except Exception:
            log.warning(
                "yandex download: direct link failed for id=%s", track.track_id, exc_info=True
            )
            await YANDEX_CIRCUIT.record_failure()
            return None
        if not link:
            log.info("yandex download: no download info for id=%s", track.track_id)
            return None
        data = await fetch_audio_bytes(link, max_bytes=MAX_TRACK_BYTES)
        if not data:
            log.info("yandex download: fetch failed for id=%s", track.track_id)
            return None
        return data, ext

    def _direct_link_sync(self, track_id: str) -> tuple[str | None, str]:
        client = make_yandex_client(self._token)
        for candidate in candidate_track_ids(track_id):
            tracks = client.tracks([candidate])
            if not tracks:
                continue
            best = pick_best_download_info(tracks[0].get_download_info())
            if best is None:
                continue
            codec = str(getattr(best, "codec", "mp3") or "mp3").lower()
            return best.get_direct_link(), codec if codec in ("mp3", "aac") else "mp3"
        return None, "mp3"


def candidate_track_ids(track_id: str) -> list[str]:
    """ID для перебора: как есть + голый ID без суффикса альбома.

    Ynison отдаёт playable_id вида '39072660:5027546', metadata-API его ест,
    а download-info иногда хочет голый ID — пробуем оба.
    """
    bare = track_id.split(":")[0]
    return [track_id] if bare == track_id else [track_id, bare]


def pick_best_download_info(infos: list[Any]) -> Any | None:
    """Выбрать максимальное качество: полный mp3, иначе любой полный, иначе любой.

    Превью-варианты (короткие сэмплы) отсекаем — как yamusic-downloader-pro:
    `codec === 'mp3' && !preview`. getattr с дефолтом — на случай старых
    версий библиотеки без поля preview.
    """
    pool = list(infos or [])
    if not pool:
        return None
    full = [i for i in pool if not getattr(i, "preview", False)]
    candidates = full or pool
    mp3 = [i for i in candidates if getattr(i, "codec", "") == "mp3"]
    return max(
        mp3 or candidates, key=lambda i: getattr(i, "bitrate_in_kbps", 0) or 0
    )
