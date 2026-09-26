"""Тесты кросс-платформенного матчинга (чистые функции + моки, без сети)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.base import TrackDTO
from app.services.crosslink import build_query, match_same_track, pick_by_duration


def _track(provider: str = "yandex", **kw) -> TrackDTO:
    base = {"title": "T", "artist": "A", "duration_ms": 180_000}
    base.update(kw)
    return TrackDTO(provider=provider, **base)


class TestBuildQuery:
    def test_query(self) -> None:
        assert build_query(_track()) == "A - T"

    def test_unknown_artist_returns_none(self) -> None:
        assert build_query(_track(artist="Unknown artist")) is None


class TestPickByDuration:
    def test_picks_closest(self) -> None:
        cands = [("far", 300_000), ("near", 182_000)]
        assert pick_by_duration(cands, 180_000) == "near"

    def test_outside_tolerance_returns_none(self) -> None:
        assert pick_by_duration([("x", 300_000)], 180_000) is None

    def test_no_expected_returns_first(self) -> None:
        assert pick_by_duration([("a", 999_000)], None) == "a"

    def test_empty_returns_none(self) -> None:
        assert pick_by_duration([], 180_000) is None


class TestMatchSameTrack:
    @pytest.mark.asyncio
    async def test_skips_own_provider(self) -> None:
        """Своя платформа не ищется: для yandex-трека — только spotify/youtube."""
        with (
            patch(
                "app.services.crosslink._spotify_app_token", new_callable=AsyncMock
            ) as app_token,
            patch("app.services.crosslink._spotify_search_sync") as sp_search,
            patch("app.services.crosslink._yandex_search_sync") as yx_search,
            patch("app.services.youtube._search_candidates_sync") as yt_search,
            patch("app.core.redis.get_cached_platform_links", new=AsyncMock(return_value=None)),
            patch("app.core.redis.set_cached_platform_links", new=AsyncMock()),
        ):
            app_token.return_value = "tok"
            sp_search.return_value = [("https://open.spotify.com/track/x", 180_000)]
            yt_search.return_value = [{"videoId": "v", "duration_seconds": 180}]
            links = await match_same_track(_track("yandex"), yandex_token="tok")
        yx_search.assert_not_called()  # своя платформа пропущена
        assert links["spotify"] == "https://open.spotify.com/track/x"
        assert links["youtube"] == "https://music.youtube.com/watch?v=v"

    @pytest.mark.asyncio
    async def test_returns_cached(self) -> None:
        with (
            patch(
                "app.core.redis.get_cached_platform_links",
                new=AsyncMock(return_value={"spotify": "u", "yandex": "v"}),
            ),
            patch("app.services.crosslink._spotify_app_token", new=AsyncMock()) as app_token,
        ):
            links = await match_same_track(_track("lastfm"))
        app_token.assert_not_called()  # сеть не трогаем при хите кеша
        assert links == {"spotify": "u", "yandex": "v"}

    @pytest.mark.asyncio
    async def test_unknown_artist_no_search(self) -> None:
        with patch(
            "app.services.crosslink._spotify_app_token", new=AsyncMock()
        ) as app_token:
            assert await match_same_track(_track(artist="Unknown artist")) == {}
        app_token.assert_not_called()
