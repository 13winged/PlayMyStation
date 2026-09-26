"""Тесты управления Spotify: play/pause/next/prev/like + статусы."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.base import BaseMusicService, TrackDTO
from app.services.spotify import SPOTIFY_CIRCUIT, SpotifyService, build_authorize_url
from tests.test_spotify_fallback import FakeResponse


class FakeControlClient:
    """Отвечает заготовленным статусом, запоминает вызовы."""

    def __init__(self, status_code: int):
        self._status = status_code
        self.calls: list[tuple[str, str, dict]] = []

    async def _respond(self, method: str, url: str, **kwargs) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        return FakeResponse(self._status)

    async def put(self, url: str, **kwargs) -> FakeResponse:
        return await self._respond("put", url, **kwargs)

    async def post(self, url: str, **kwargs) -> FakeResponse:
        return await self._respond("post", url, **kwargs)


def _patch_control(status_code: int) -> tuple[FakeControlClient, object, object]:
    async def _call(func):
        return await func()

    client = FakeControlClient(status_code)
    return (
        client,
        patch("app.services.spotify._get_spotify_client", return_value=client),
        patch.object(SPOTIFY_CIRCUIT, "call", side_effect=_call),
    )


def _track() -> TrackDTO:
    return TrackDTO(title="T", artist="A", provider="spotify", track_id="abc123")


class TestControlStatusMapping:
    @pytest.mark.asyncio
    async def test_pause_ok(self) -> None:
        client, p1, p2 = _patch_control(204)
        with p1, p2:
            assert await SpotifyService("token").set_playing(False) == "ok"
        assert client.calls[0][1].endswith("/me/player/pause")

    @pytest.mark.asyncio
    async def test_play_ok(self) -> None:
        client, p1, p2 = _patch_control(204)
        with p1, p2:
            assert await SpotifyService("token").set_playing(True) == "ok"
        assert client.calls[0][1].endswith("/me/player/play")

    @pytest.mark.asyncio
    async def test_next_and_previous(self) -> None:
        client, p1, p2 = _patch_control(204)
        with p1, p2:
            svc = SpotifyService("token")
            assert await svc.skip("next") == "ok"
            assert await svc.skip("previous") == "ok"
        assert client.calls[0][1].endswith("/me/player/next")
        assert client.calls[1][1].endswith("/me/player/previous")

    @pytest.mark.asyncio
    async def test_like_sends_track_id(self) -> None:
        client, p1, p2 = _patch_control(200)
        with p1, p2:
            assert await SpotifyService("token").like_track(_track()) == "ok"
        _method, url, kwargs = client.calls[0]
        assert url.endswith("/me/tracks")
        assert kwargs["params"] == {"ids": "abc123"}

    @pytest.mark.asyncio
    async def test_like_without_id_errors(self) -> None:
        _, p1, p2 = _patch_control(200)
        with p1, p2:
            track = TrackDTO(title="T", artist="A", provider="spotify")
            assert await SpotifyService("token").like_track(track) == "error"

    @pytest.mark.asyncio
    async def test_403_maps_to_premium(self) -> None:
        _, p1, p2 = _patch_control(403)
        with p1, p2:
            assert await SpotifyService("token").set_playing(False) == "premium"

    @pytest.mark.asyncio
    async def test_404_maps_to_no_device(self) -> None:
        _, p1, p2 = _patch_control(404)
        with p1, p2:
            assert await SpotifyService("token").set_playing(False) == "no_device"

    @pytest.mark.asyncio
    async def test_500_maps_to_error(self) -> None:
        _, p1, p2 = _patch_control(500)
        with p1, p2:
            assert await SpotifyService("token").set_playing(False) == "error"


class TestControlCapabilities:
    def test_spotify_flags(self) -> None:
        assert SpotifyService.supports_control is True
        assert SpotifyService.supports_like is True

    def test_base_defaults_unsupported(self) -> None:
        assert BaseMusicService.supports_control is False
        assert BaseMusicService.supports_like is False


class TestControlScopes:
    def test_authorize_url_requests_control_scopes(self) -> None:
        url = build_authorize_url(state="1")
        assert "user-modify-playback-state" in url
        assert "user-library-modify" in url


def test_track_kb_controls_row() -> None:
    from app.bot.keyboards import track_kb

    kb = track_kb(False, None, "ru", controls=True, playing=True)
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert "⏸ Пауза" in texts
    assert "⏭ Дальше" in texts
    assert "❤️ В любимые" in texts

    kb_off = track_kb(False, None, "ru", controls=False)
    texts_off = [b.text for row in kb_off.inline_keyboard for b in row]
    assert not any("⏸" in (x or "") or "⏭" in (x or "") for x in texts_off)
