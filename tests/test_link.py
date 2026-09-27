"""Тесты скачивания по ссылке: парсер URL + метаданные (без сети)."""

from __future__ import annotations

import sys
import types

import pytest

from app.bot.handlers.link import parse_track_link
from app.services.crosslink import spotify_meta_to_dto


class TestParseTrackLink:
    def test_spotify_track(self) -> None:
        assert parse_track_link(
            "https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDw0G9?si=x"
        ) == ("spotify", "6rqhFgbbKwnb9MLmUQDw0G9")

    def test_spotify_intl_track(self) -> None:
        assert parse_track_link(
            "https://open.spotify.com/intl-ru/track/6rqhFgbbKwnb9MLmUQDw0G9"
        ) == ("spotify", "6rqhFgbbKwnb9MLmUQDw0G9")

    def test_spotify_album_is_not_a_track(self) -> None:
        assert parse_track_link("https://open.spotify.com/album/abc123XYZ9") is None

    def test_yandex_track(self) -> None:
        assert parse_track_link(
            "https://music.yandex.ru/album/5027546/track/39072660"
        ) == ("yandex", "39072660:5027546")

    def test_yandex_album_is_not_a_track(self) -> None:
        assert parse_track_link("https://music.yandex.ru/album/5027546") is None

    def test_youtube_watch(self) -> None:
        assert parse_track_link(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s"
        ) == ("youtube", "dQw4w9WgXcQ")

    def test_youtu_be(self) -> None:
        assert parse_track_link("https://youtu.be/dQw4w9WgXcQ") == (
            "youtube",
            "dQw4w9WgXcQ",
        )

    def test_ytmusic_watch(self) -> None:
        assert parse_track_link(
            "https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=xyz"
        ) == ("youtube", "dQw4w9WgXcQ")

    def test_garbage_returns_none(self) -> None:
        assert parse_track_link("привет, как дела?") is None
        assert parse_track_link("") is None
        assert parse_track_link("https://example.com/track/123") is None

    def test_link_inside_text(self) -> None:
        assert parse_track_link(
            "слушай https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDw0G9 крутое!"
        ) == ("spotify", "6rqhFgbbKwnb9MLmUQDw0G9")


class TestSpotifyMetaToDto:
    def test_maps_fields(self) -> None:
        data = {
            "id": "abc",
            "name": "Song",
            "artists": [{"name": "A"}, {"name": "B"}],
            "album": {"name": "Alb", "images": [{"url": "https://img"}]},
            "duration_ms": 200_000,
            "preview_url": "https://prev",
        }
        dto = spotify_meta_to_dto(data, "https://open.spotify.com/track/abc")
        assert dto.title == "Song"
        assert dto.artist == "A, B"
        assert dto.track_id == "abc"
        assert dto.provider == "spotify"
        assert dto.track_url == "https://open.spotify.com/track/abc"


@pytest.mark.asyncio
async def test_youtube_video_meta(monkeypatch) -> None:
    """Метаданные видео через стаб ytmusicapi."""
    import app.services.youtube as yt_mod

    class FakeYT:
        def __init__(self, *args, **kwargs):
            pass

        def get_song(self, video_id: str):
            assert video_id == "vid123"
            return {
                "videoDetails": {
                    "title": "T",
                    "author": "A",
                    "lengthSeconds": "213",
                    "thumbnail": {"thumbnails": [{"url": "https://img"}]},
                }
            }

    mod = types.ModuleType("ytmusicapi")
    mod.YTMusic = FakeYT
    monkeypatch.setitem(sys.modules, "ytmusicapi", mod)

    dto = await yt_mod.youtube_video_meta("vid123")
    assert dto is not None
    assert dto.title == "T"
    assert dto.artist == "A"
    assert dto.duration_ms == 213_000
    assert dto.track_id == "vid123"
    assert dto.provider == "youtube"
