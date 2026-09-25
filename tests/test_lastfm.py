"""Тесты Last.fm-провайдера."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Integration
from app.services.factory import build_service
from app.services.lastfm import LastFmService


def _raw_track(nowplaying: bool = True) -> dict:
    t = {
        "name": "Song",
        "artist": {"#text": "Artist"},
        "album": {"#text": "Album"},
        "url": "https://www.last.fm/music/a/_/s",
        "image": [{"#text": ""}, {"#text": "https://img/large.png"}],
    }
    if nowplaying:
        t["@attr"] = {"nowplaying": "true"}
    else:
        t["date"] = {"uts": "123", "#text": "now"}
    return t


def test_to_dto_nowplaying() -> None:
    dto = LastFmService._to_dto(_raw_track(nowplaying=True))
    assert dto.title == "Song"
    assert dto.artist == "Artist"
    assert dto.album == "Album"
    assert dto.is_playing is True
    assert dto.cover_url == "https://img/large.png"
    assert dto.provider == "lastfm"
    assert dto.preview_url is None


def test_to_dto_last_played() -> None:
    dto = LastFmService._to_dto(_raw_track(nowplaying=False))
    assert dto.is_playing is False


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, response: FakeResponse):
        self._response = response

    async def get(self, url: str, **kwargs) -> FakeResponse:
        return self._response


def _client_patch(response: FakeResponse):
    async def _call(func):
        return await func()

    from app.services.lastfm import LASTFM_CIRCUIT

    return (
        patch(
            "app.services.lastfm._get_lastfm_client",
            return_value=FakeClient(response),
        ),
        patch.object(LASTFM_CIRCUIT, "call", side_effect=_call),
    )


@pytest.mark.asyncio
async def test_get_currently_playing_dict_track() -> None:
    """Один трек API отдаёт объектом, а не списком — обрабатываем."""
    payload = {"recenttracks": {"track": _raw_track(True)}}
    client_patch, circuit_patch = _client_patch(FakeResponse(200, payload))
    with client_patch, circuit_patch, patch(
        "app.services.lastfm.get_settings",
        return_value=MagicMock(lastfm_api_key="key"),
    ):
        track = await LastFmService("someuser").get_currently_playing()
    assert track is not None
    assert track.title == "Song"
    assert track.is_playing is True


@pytest.mark.asyncio
async def test_get_currently_playing_list_and_empty() -> None:
    payload = {"recenttracks": {"track": [_raw_track(False)]}}
    client_patch, circuit_patch = _client_patch(FakeResponse(200, payload))
    with client_patch, circuit_patch, patch(
        "app.services.lastfm.get_settings",
        return_value=MagicMock(lastfm_api_key="key"),
    ):
        track = await LastFmService("someuser").get_currently_playing()
    assert track is not None
    assert track.is_playing is False

    empty_patch, empty_circuit = _client_patch(FakeResponse(200, {"recenttracks": {"track": []}}))
    with empty_patch, empty_circuit, patch(
        "app.services.lastfm.get_settings",
        return_value=MagicMock(lastfm_api_key="key"),
    ):
        assert await LastFmService("someuser").get_currently_playing() is None


@pytest.mark.asyncio
async def test_build_service_lastfm_uses_service_user_id() -> None:
    integration = Integration(
        id=1, user_id=1, provider="lastfm", access_token=None, service_user_id="someuser"
    )
    session = MagicMock(spec=AsyncSession)
    result = await build_service(integration, session)
    assert result is not None
    assert result.provider == "lastfm"


@pytest.mark.asyncio
async def test_build_service_lastfm_without_username_returns_none() -> None:
    integration = Integration(
        id=1, user_id=1, provider="lastfm", access_token=None, service_user_id=None
    )
    session = MagicMock(spec=AsyncSession)
    assert await build_service(integration, session) is None
