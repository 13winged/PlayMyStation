"""Тесты YandexMusicService через Ynison-снимок (без сети)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.base import TrackDTO
from app.services.yandex import YandexMusicService
from app.services.ynison import YnisonNowPlaying, YnisonPlayableItem


def _snapshot(paused: bool = False) -> YnisonNowPlaying:
    return YnisonNowPlaying(
        items=[
            YnisonPlayableItem(
                playable_id="123", album_id="1", title="T", currently_playing=True
            )
        ],
        progress_ms=42_000,
        duration_ms=180_000,
        paused=paused,
    )


def _track() -> TrackDTO:
    return TrackDTO(title="T", artist="A", provider="yandex", is_playing=True)


@pytest.mark.asyncio
async def test_ynison_snapshot_overlays_progress() -> None:
    """Realtime-снимок накладывает прогресс и статус паузы на трек."""
    svc = YandexMusicService("token")
    with patch(
        "app.services.yandex.Ynison"
    ) as mock_ynison, patch.object(
        YandexMusicService, "_fetch_track_sync", return_value=_track()
    ):
        mock_ynison.return_value.get_now_playing = AsyncMock(return_value=_snapshot())
        track = await svc.get_currently_playing()
    assert track is not None
    assert track.progress_ms == 42_000
    assert track.duration_ms == 180_000
    assert track.is_playing is True


@pytest.mark.asyncio
async def test_ynison_paused_marks_not_playing() -> None:
    svc = YandexMusicService("token")
    with patch(
        "app.services.yandex.Ynison"
    ) as mock_ynison, patch.object(
        YandexMusicService, "_fetch_track_sync", return_value=_track()
    ):
        mock_ynison.return_value.get_now_playing = AsyncMock(
            return_value=_snapshot(paused=True)
        )
        track = await svc.get_currently_playing()
    assert track is not None
    assert track.is_playing is False


@pytest.mark.asyncio
async def test_ynison_failure_falls_back_to_queue() -> None:
    """Ynison недоступен — откатываемся на эвристику очереди."""
    from app.services.ynison import YnisonError

    svc = YandexMusicService("token")
    with patch(
        "app.services.yandex.Ynison"
    ) as mock_ynison, patch.object(
        YandexMusicService, "_fetch_queue_sync", return_value=_track()
    ):
        mock_ynison.return_value.get_now_playing = AsyncMock(
            side_effect=YnisonError("boom")
        )
        track = await svc.get_currently_playing()
    assert track is not None
    assert track.title == "T"


@pytest.mark.asyncio
async def test_empty_queue_returns_none() -> None:
    """Ни Ynison, ни очередь ничего не дали — None (не ошибка)."""
    from app.services.ynison import YnisonNowPlaying

    svc = YandexMusicService("token")
    empty = YnisonNowPlaying(items=[], progress_ms=None, duration_ms=None, paused=True)
    with patch(
        "app.services.yandex.Ynison"
    ) as mock_ynison, patch.object(
        YandexMusicService, "_fetch_queue_sync", return_value=None
    ):
        mock_ynison.return_value.get_now_playing = AsyncMock(return_value=empty)
        assert await svc.get_currently_playing() is None
