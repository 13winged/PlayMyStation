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
        from yandex_music import Client  # lazy import — тяжёлая зависимость

        client = Client(self._token).init()
        tracks = client.tracks([track_id])
        if not tracks:
            return None
        return self._track_dto_from_full(tracks[0])

    def _fetch_queue_sync(self) -> TrackDTO | None:
        from yandex_music import Client  # lazy import — тяжёлая зависимость

        client = Client(self._token).init()
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

    async def download_track(self, track: TrackDTO) -> tuple[bytes, str] | None:
        """Скачать полный трек через прямые ссылки (токен юзера, его подписка)."""
        if not track.track_id:
            return None
        try:
            link, ext = await asyncio.to_thread(
                self._direct_link_sync, track.track_id
            )
        except Exception:  # noqa: BLE001 — API Яндекса нестабилен
            await YANDEX_CIRCUIT.record_failure()
            return None
        if not link:
            return None
        data = await fetch_audio_bytes(link, max_bytes=MAX_TRACK_BYTES)
        if not data:
            return None
        return data, ext

    def _direct_link_sync(self, track_id: str) -> tuple[str | None, str]:
        from yandex_music import Client  # lazy import — тяжёлая зависимость

        client = Client(self._token).init()
        tracks = client.tracks([track_id])
        if not tracks:
            return None, "mp3"
        best = pick_best_download_info(tracks[0].get_download_info())
        if best is None:
            return None, "mp3"
        codec = str(getattr(best, "codec", "mp3") or "mp3").lower()
        return best.get_direct_link(), codec if codec in ("mp3", "aac") else "mp3"


def pick_best_download_info(infos: list[Any]) -> Any | None:
    """Выбрать максимальное качество: сначала mp3, иначе любой кодек."""
    pool = list(infos or [])
    if not pool:
        return None
    mp3 = [i for i in pool if getattr(i, "codec", "") == "mp3"]
    candidates = mp3 or pool
    return max(candidates, key=lambda i: getattr(i, "bitrate_in_kbps", 0) or 0)
