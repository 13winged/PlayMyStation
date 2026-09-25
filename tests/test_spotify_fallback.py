"""Тесты Spotify-фолбэка на recently-played (403/204 realtime API)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.spotify import SPOTIFY_CIRCUIT, SpotifyService


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | list | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeClient:
    """Отдаёт заготовленные ответы по URL (currently-playing / recently-played)."""

    def __init__(self, now_playing: FakeResponse, recently_played: FakeResponse):
        self._now_playing = now_playing
        self._recently_played = recently_played

    async def get(self, url: str, **kwargs) -> FakeResponse:
        if "recently-played" in url:
            return self._recently_played
        return self._now_playing


def _recent_payload() -> dict:
    return {
        "items": [
            {
                "track": {
                    "name": "Last Song",
                    "artists": [{"name": "Artist"}],
                    "album": {"name": "Album", "images": []},
                    "duration_ms": 200_000,
                    "external_urls": {"spotify": "https://open.spotify.com/track/x"},
                    "preview_url": "https://p.scdn.co/mp3-preview/x",
                }
            }
        ]
    }


def _patch_client(now_playing: FakeResponse, recently_played: FakeResponse):
    async def _call(func):
        return await func()

    return (
        patch(
            "app.services.spotify._get_spotify_client",
            return_value=FakeClient(now_playing, recently_played),
        ),
        patch.object(SPOTIFY_CIRCUIT, "call", side_effect=_call),
    )


@pytest.mark.asyncio
async def test_fallback_on_403() -> None:
    """403 realtime (free-аккаунт) → берём последний трек из recently-played."""
    client_patch, circuit_patch = _patch_client(
        FakeResponse(403, {"error": {"reason": "PREMIUM_REQUIRED"}}),
        FakeResponse(200, _recent_payload()),
    )
    with client_patch, circuit_patch:
        track = await SpotifyService("token").get_currently_playing()
    assert track is not None
    assert track.title == "Last Song"
    assert track.is_playing is False
    assert track.provider == "spotify"
    assert track.preview_url == "https://p.scdn.co/mp3-preview/x"


@pytest.mark.asyncio
async def test_fallback_on_204() -> None:
    """204 (ничего не играет) → тоже смотрим историю."""
    client_patch, circuit_patch = _patch_client(
        FakeResponse(204), FakeResponse(200, _recent_payload())
    )
    with client_patch, circuit_patch:
        track = await SpotifyService("token").get_currently_playing()
    assert track is not None
    assert track.title == "Last Song"
    assert track.is_playing is False


@pytest.mark.asyncio
async def test_no_fallback_without_scope() -> None:
    """Старый токен без скоупа recently-played → 403 и там → None."""
    client_patch, circuit_patch = _patch_client(
        FakeResponse(403), FakeResponse(403)
    )
    with client_patch, circuit_patch:
        track = await SpotifyService("token").get_currently_playing()
    assert track is None
