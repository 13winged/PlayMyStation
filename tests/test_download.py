"""Тесты докачки аудио: выбор качества, track_id, дефолты (без сети)."""

from types import SimpleNamespace

import pytest

from app.services.base import BaseMusicService, TrackDTO
from app.services.spotify import SpotifyService
from app.services.yandex import YandexMusicService, pick_best_download_info
from app.services.youtube import YouTubeMusicService, parse_duration_seconds, pick_match


def _track(provider: str = "yandex", **kw) -> TrackDTO:
    return TrackDTO(title="T", artist="A", provider=provider, **kw)


class TestBaseDownload:
    @pytest.mark.asyncio
    async def test_base_download_not_supported(self) -> None:
        class Dummy(BaseMusicService):
            provider = "dummy"

            async def get_currently_playing(self):
                return None

        assert await Dummy().download_track(_track()) is None


class TestTrackId:
    def test_youtube_dto_carries_video_id(self) -> None:
        dto = YouTubeMusicService._to_dto({"videoId": "abc", "title": "T"})
        assert dto.track_id == "abc"

    def test_yandex_dto_carries_track_id(self) -> None:
        svc = YandexMusicService("token")
        full = SimpleNamespace(
            id=123456,
            title="T",
            artists=[],
            albums=[],
            cover_uri=None,
            duration_ms=200000,
        )
        dto = svc._track_dto_from_full(full)
        assert dto.track_id == "123456"

    def test_dto_track_id_defaults_to_none(self) -> None:
        assert _track().track_id is None


class TestPickBestDownloadInfo:
    def test_prefers_mp3_with_max_bitrate(self) -> None:
        infos = [
            SimpleNamespace(codec="aac", bitrate_in_kbps=256),
            SimpleNamespace(codec="mp3", bitrate_in_kbps=128),
            SimpleNamespace(codec="mp3", bitrate_in_kbps=320),
        ]
        best = pick_best_download_info(infos)
        assert best is not None
        assert best.bitrate_in_kbps == 320
        assert best.codec == "mp3"

    def test_falls_back_to_any_codec_without_mp3(self) -> None:
        infos = [SimpleNamespace(codec="aac", bitrate_in_kbps=256)]
        assert pick_best_download_info(infos) is infos[0]

    def test_empty_returns_none(self) -> None:
        assert pick_best_download_info([]) is None


class TestSpotifyDownload:
    @pytest.mark.asyncio
    async def test_no_preview_no_download(self) -> None:
        svc = SpotifyService("token")
        assert await svc.download_track(_track("spotify")) is None

    @pytest.mark.asyncio
    async def test_yandex_without_track_id_no_download(self) -> None:
        svc = YandexMusicService("token")
        assert await svc.download_track(_track("yandex")) is None

    @pytest.mark.asyncio
    async def test_youtube_without_track_id_no_download(self) -> None:
        svc = YouTubeMusicService("{}")
        assert await svc.download_track(_track("youtube")) is None


class TestParseDuration:
    def test_mm_ss(self) -> None:
        assert parse_duration_seconds("4:38") == 278

    def test_hh_mm_ss(self) -> None:
        assert parse_duration_seconds("1:02:03") == 3723

    def test_seconds_number(self) -> None:
        assert parse_duration_seconds(213) == 213
        assert parse_duration_seconds(213.7) == 213

    def test_garbage_returns_none(self) -> None:
        assert parse_duration_seconds(None) is None
        assert parse_duration_seconds("live") is None
        assert parse_duration_seconds("") is None
        assert parse_duration_seconds(0) is None


class TestPickMatch:
    def test_picks_closest_duration(self) -> None:
        cands = [
            {"videoId": "far", "duration_seconds": 300},
            {"videoId": "near", "duration_seconds": 215},
        ]
        assert pick_match(cands, 213_000) == "near"

    def test_outside_tolerance_returns_none(self) -> None:
        cands = [{"videoId": "x", "duration_seconds": 300}]
        assert pick_match(cands, 180_000) is None

    def test_no_expected_returns_first(self) -> None:
        cands = [{"videoId": "a", "duration_seconds": 999}]
        assert pick_match(cands, None) == "a"

    def test_empty_returns_none(self) -> None:
        assert pick_match([], 180_000) is None

    def test_unknown_duration_accepts_best(self) -> None:
        cands = [{"videoId": "u", "duration_seconds": None}]
        assert pick_match(cands, 180_000) == "u"
