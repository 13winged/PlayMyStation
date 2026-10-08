"""Регрессии локального аудита: OAuth, выбор сервиса и метрики."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.bot.handlers.start import cb_set_active
from app.core.redis import consume_oauth_state
from app.services.base import TrackDTO
from app.services.factory import resolve_now_playing
from app.web.app import create_web_app
from app.web.oauth import _verify_state


@pytest.mark.parametrize("state", ["42", "", "42:", ":token", "abc:token"])
async def test_invalid_state_never_consumes_token(state):
    with patch("app.core.redis.consume_oauth_state", new_callable=AsyncMock) as consume:
        with pytest.raises(HTTPException) as error:
            await _verify_state(state)
        assert error.value.status_code == 400
        consume.assert_not_awaited()


async def test_oauth_state_consumption_is_atomic():
    redis = AsyncMock()
    redis.getdel.side_effect = ["42", None]
    with patch("app.core.redis.get_redis", new_callable=AsyncMock, return_value=redis):
        assert await consume_oauth_state("token") == 42
        assert await consume_oauth_state("token") is None
    redis.get.assert_not_awaited()
    redis.delete.assert_not_awaited()


async def test_switch_invalidates_cache():
    cb = SimpleNamespace(data="svc:active:youtube", answer=AsyncMock())
    user = SimpleNamespace(id=1, telegram_id=42, active_provider="spotify", language="ru")
    with (
        patch("app.bot.handlers.start.repo.set_active_provider", new_callable=AsyncMock),
        patch("app.bot.handlers.start.repo.list_integrations", new_callable=AsyncMock,
              return_value=[]),
        patch("app.bot.handlers.start.edit_markup_safe", new_callable=AsyncMock),
        patch("app.bot.handlers.start.invalidate_now_playing_cache",
              new_callable=AsyncMock) as invalidate,
    ):
        await cb_set_active(cb, AsyncMock(), user)
    invalidate.assert_awaited_once_with(42)


@pytest.mark.parametrize("active,bound", [("youtube", ["spotify"]), ("all", [])])
async def test_cache_cannot_return_wrong_or_disconnected_provider(active, bound):
    track = TrackDTO(provider="spotify", title="Old", artist="Test")
    with patch("app.services.factory.get_cached_now_playing", new_callable=AsyncMock,
               return_value=track):
        result = await resolve_now_playing(
            [SimpleNamespace(provider=p) for p in bound], AsyncMock(), active, 42
        )
    assert result is None


def test_unknown_urls_share_one_metrics_label():
    with TestClient(create_web_app()) as client:
        for path in ("/regression-random-a", "/regression-random-b"):
            assert client.get(path).status_code == 404
        assert client.get("/health").status_code == 200
        body = client.get("/metrics").text
    assert "regression-random" not in body
    assert "__unmatched__" in body
    assert '/health' in body
