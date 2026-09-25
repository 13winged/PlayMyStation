"""Yandex Music: работа по OAuth-токену.

У Яндекс.Музыки нет публичного 'currently playing' эндпоинта,
поэтому стратегия: читаем очередь (queues) + статус (rotor station feedback).
Возвращаем текущий трек очереди как наиболее вероятный 'now playing'.
Sync-библиотека yandex-music выполняется в asyncio.to_thread.
"""

from __future__ import annotations

import asyncio

from app.core.retry import YANDEX_CIRCUIT
from app.services.base import BaseMusicService, TrackDTO


class YandexMusicService(BaseMusicService):
    provider = "yandex"

    def __init__(self, oauth_token: str) -> None:
        self._token = oauth_token

    def _fetch_sync(self) -> TrackDTO | None:
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
            progress_ms=None,  # API очереди прогресс не отдаёт
            is_playing=True,  # очередь существует — считаем активным (уточняется клиентом)
            cover_url=cover,
            track_url=track_url,
            provider="yandex",
        )

    async def get_currently_playing(self) -> TrackDTO | None:
        if YANDEX_CIRCUIT.is_open:
            return None  # сервис недавно сыпал ошибками — не дёргаем API
        try:
            track = await asyncio.to_thread(self._fetch_sync)
        except Exception:  # noqa: BLE001 — API Яндекса нестабилен
            await YANDEX_CIRCUIT.record_failure()
            return None
        # Пустая очередь — штатная ситуация, а не ошибка сервиса.
        if track is not None:
            await YANDEX_CIRCUIT.record_success()
        return track
