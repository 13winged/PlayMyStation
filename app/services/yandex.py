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

from app.core.retry import YANDEX_CIRCUIT
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
