"""Тесты фабрики сервисов с моками."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Integration
from app.services.base import TrackDTO
from app.services.factory import build_service, resolve_now_playing


class ServiceError(Exception):
    """Исключение для имитации ошибки сервиса."""


class MockService:
    """Мок сервиса для тестов."""

    def __init__(self, provider: str, track: TrackDTO | None = None, should_fail: bool = False):
        self.provider = provider
        self._track = track
        self._should_fail = should_fail

    async def get_currently_playing(self) -> TrackDTO | None:
        if self._should_fail:
            raise ServiceError("Service error")
        return self._track


@pytest.mark.asyncio
async def test_build_service_spotify_returns_none_when_no_token() -> None:
    """build_service возвращает None, если нет access_token."""
    integration = Integration(
        id=1,
        user_id=1,
        provider="spotify",
        access_token=None,
        refresh_token=None,
    )
    session = MagicMock(spec=AsyncSession)

    with patch("app.services.factory.repo.decrypted_access", return_value=None):
        result = await build_service(integration, session)
        assert result is None


@pytest.mark.asyncio
async def test_build_service_yandex_returns_service() -> None:
    """build_service создаёт YandexMusicService с токеном."""
    integration = Integration(
        id=1,
        user_id=1,
        provider="yandex",
        access_token="encrypted_token",
    )
    session = MagicMock(spec=AsyncSession)

    with patch("app.services.factory.repo.decrypted_access", return_value="valid_token"):
        result = await build_service(integration, session)
        assert result is not None
        assert result.provider == "yandex"


@pytest.mark.asyncio
async def test_build_service_youtube_returns_service() -> None:
    """build_service создаёт YouTubeMusicService с auth-JSON."""
    integration = Integration(
        id=1,
        user_id=1,
        provider="youtube",
        access_token="encrypted_auth",
    )
    session = MagicMock(spec=AsyncSession)

    with patch("app.services.factory.repo.decrypted_access", return_value='{"cookie": "x"}'):
        result = await build_service(integration, session)
        assert result is not None
        assert result.provider == "youtube"


@pytest.mark.asyncio
async def test_build_service_youtube_returns_none_when_no_auth() -> None:
    """build_service возвращает None, если нет auth-JSON."""
    integration = Integration(
        id=1,
        user_id=1,
        provider="youtube",
        access_token=None,
    )
    session = MagicMock(spec=AsyncSession)

    with patch("app.services.factory.repo.decrypted_access", return_value=None):
        result = await build_service(integration, session)
        assert result is None


@pytest.mark.asyncio
async def test_resolve_now_playing_single_service() -> None:
    """resolve_now_playing с одним сервисом возвращает его трек."""
    track = TrackDTO(
        title="Single Track",
        artist="Artist",
        provider="spotify",
        is_playing=True,
    )
    mock_service = MockService("spotify", track)

    with patch("app.services.factory.build_service", return_value=mock_service):
        integrations = [
            Integration(id=1, user_id=1, provider="spotify", access_token="token")
        ]
        session = MagicMock(spec=AsyncSession)

        result = await resolve_now_playing(integrations, session, "spotify")
        assert result == track


@pytest.mark.asyncio
async def test_resolve_now_playing_all_mode_prefers_playing() -> None:
    """В режиме ALL приоритет у is_playing=True."""
    playing_track = TrackDTO(
        title="Playing",
        artist="Artist",
        provider="spotify",
        is_playing=True,
    )
    paused_track = TrackDTO(
        title="Paused",
        artist="Artist",
        provider="yandex",
        is_playing=False,
    )

    spotify_svc = MockService("spotify", playing_track)
    yandex_svc = MockService("yandex", paused_track)

    async def mock_build(integ, session):
        if integ.provider == "spotify":
            return spotify_svc
        if integ.provider == "yandex":
            return yandex_svc
        return None

    with patch("app.services.factory.build_service", side_effect=mock_build):
        integrations = [
            Integration(id=1, user_id=1, provider="spotify", access_token="token"),
            Integration(id=2, user_id=1, provider="yandex", access_token="token"),
        ]
        session = MagicMock(spec=AsyncSession)

        result = await resolve_now_playing(integrations, session, "all")
        assert result == playing_track  # должен выбрать играющий


@pytest.mark.asyncio
async def test_resolve_now_playing_all_mode_fallback_to_first() -> None:
    """В режиме ALL если никто не играет — возвращает первый."""
    track1 = TrackDTO(title="First", artist="A", provider="spotify", is_playing=False)
    track2 = TrackDTO(title="Second", artist="B", provider="yandex", is_playing=False)

    svc1 = MockService("spotify", track1)
    svc2 = MockService("yandex", track2)

    async def mock_build(integ, session):
        if integ.provider == "spotify":
            return svc1
        if integ.provider == "yandex":
            return svc2
        return None

    with patch("app.services.factory.build_service", side_effect=mock_build):
        integrations = [
            Integration(id=1, user_id=1, provider="spotify", access_token="token"),
            Integration(id=2, user_id=1, provider="yandex", access_token="token"),
        ]
        session = MagicMock(spec=AsyncSession)

        result = await resolve_now_playing(integrations, session, "all")
        assert result == track1  # первый в списке


@pytest.mark.asyncio
async def test_resolve_now_playing_handles_exceptions() -> None:
    """resolve_now_playing игнорирует исключения от сервисов."""
    good_track = TrackDTO(title="Good", artist="A", provider="spotify", is_playing=True)
    good_svc = MockService("spotify", good_track)
    bad_svc = MockService("yandex", should_fail=True)

    async def mock_build(integ, session):
        if integ.provider == "spotify":
            return good_svc
        if integ.provider == "yandex":
            return bad_svc
        return None

    with patch("app.services.factory.build_service", side_effect=mock_build):
        integrations = [
            Integration(id=1, user_id=1, provider="spotify", access_token="token"),
            Integration(id=2, user_id=1, provider="yandex", access_token="token"),
        ]
        session = MagicMock(spec=AsyncSession)

        result = await resolve_now_playing(integrations, session, "all")
        assert result == good_track


@pytest.mark.asyncio
async def test_resolve_now_playing_caches_result() -> None:
    """resolve_now_playing кэширует результат в Redis (проверяем вызов set_cached)."""
    track = TrackDTO(title="Cached", artist="A", provider="spotify", is_playing=True)
    mock_service = MockService("spotify", track)

    with patch("app.services.factory.build_service", return_value=mock_service), \
         patch("app.services.factory.set_cached_now_playing", new_callable=AsyncMock) as mock_cache, \
         patch("app.services.factory.get_cached_now_playing", new_callable=AsyncMock, return_value=None):

        integrations = [Integration(id=1, user_id=1, provider="spotify", access_token="token")]
        session = MagicMock(spec=AsyncSession)

        result = await resolve_now_playing(integrations, session, "spotify", telegram_id=12345)
        assert result == track
        mock_cache.assert_awaited_once_with(12345, track)


@pytest.mark.asyncio
async def test_resolve_now_playing_returns_cached() -> None:
    """resolve_now_playing возвращает кэшированное значение, если есть."""
    cached_track = TrackDTO(title="Cached", artist="A", provider="spotify", is_playing=True)
    fresh_track = TrackDTO(title="Fresh", artist="B", provider="spotify", is_playing=True)

    mock_service = MockService("spotify", fresh_track)

    with patch("app.services.factory.build_service", return_value=mock_service), \
         patch("app.services.factory.get_cached_now_playing", new_callable=AsyncMock, return_value=cached_track), \
         patch("app.services.factory.set_cached_now_playing", new_callable=AsyncMock) as mock_cache:

        integrations = [Integration(id=1, user_id=1, provider="spotify", access_token="token")]
        session = MagicMock(spec=AsyncSession)

        result = await resolve_now_playing(integrations, session, "spotify", telegram_id=12345)
        assert result == cached_track
        # build_service не должен вызываться, если есть кэш
        # но мы не можем легко это проверить через mock_build, так что просто проверяем результат
        mock_cache.assert_not_called()  # не должно перезаписывать кэш


@pytest.mark.asyncio
async def test_resolve_now_playing_slow_service_times_out() -> None:
    """Зависший сервис отваливается по таймауту и не блокирует /now (bulkhead)."""
    import asyncio as _asyncio

    fast_track = TrackDTO(title="Fast", artist="A", provider="spotify", is_playing=True)

    class SlowService:
        provider = "yandex"

        async def get_currently_playing(self) -> TrackDTO | None:
            await _asyncio.sleep(30)
            return TrackDTO(title="Slow", artist="B", provider="yandex", is_playing=True)

    fast_svc = MockService("spotify", fast_track)
    slow_svc = SlowService()

    async def mock_build(integ, session):
        if integ.provider == "spotify":
            return fast_svc
        if integ.provider == "yandex":
            return slow_svc
        return None

    with patch("app.services.factory.build_service", side_effect=mock_build), \
         patch("app.services.factory.NOW_PLAYING_TIMEOUT", 0.2):
        integrations = [
            Integration(id=1, user_id=1, provider="spotify", access_token="token"),
            Integration(id=2, user_id=1, provider="yandex", access_token="token"),
        ]
        session = MagicMock(spec=AsyncSession)

        result = await resolve_now_playing(integrations, session, "all")
        assert result == fast_track


@pytest.mark.asyncio
async def test_resolve_now_playing_all_slow_returns_none() -> None:
    """Если все сервисы висят — возвращаем None, а не висим вечно."""
    import asyncio as _asyncio

    class SlowService:
        provider = "spotify"

        async def get_currently_playing(self) -> TrackDTO | None:
            await _asyncio.sleep(30)
            return None

    with patch("app.services.factory.build_service", return_value=SlowService()), \
         patch("app.services.factory.NOW_PLAYING_TIMEOUT", 0.2):
        integrations = [Integration(id=1, user_id=1, provider="spotify", access_token="token")]
        session = MagicMock(spec=AsyncSession)

        result = await resolve_now_playing(integrations, session, "spotify")
        assert result is None