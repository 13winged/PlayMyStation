"""Тесты OAuth CSRF-state: сборка ссылки и верификация callback."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.services.spotify import build_authorize_url, build_authorize_url_secure
from app.web.oauth import _verify_state


class TestSecureAuthorizeUrl:
    @pytest.mark.asyncio
    async def test_state_contains_token(self) -> None:
        with patch(
            "app.core.redis.save_oauth_state", new_callable=AsyncMock
        ) as save:
            url = await build_authorize_url_secure(762446267)
        assert "state=762446267%3A" in url or "state=762446267:" in url
        save.assert_awaited_once()

    def test_plain_builder_keeps_telegram_id(self) -> None:
        assert "state=42" in build_authorize_url(42)


class TestVerifyState:
    @pytest.mark.asyncio
    async def test_valid_token(self) -> None:
        with patch(
            "app.core.redis.consume_oauth_state", new_callable=AsyncMock, return_value=762446267
        ):
            assert await _verify_state("762446267:tok123") == 762446267

    @pytest.mark.asyncio
    async def test_unknown_token_rejected(self) -> None:
        with (
            patch(
                "app.core.redis.consume_oauth_state", new_callable=AsyncMock, return_value=None
            ),
            pytest.raises(HTTPException),
        ):
            await _verify_state("762446267:tok123")

    @pytest.mark.asyncio
    async def test_mismatched_id_rejected(self) -> None:
        with (
            patch(
                "app.core.redis.consume_oauth_state", new_callable=AsyncMock, return_value=111
            ),
            pytest.raises(HTTPException),
        ):
            await _verify_state("762446267:tok123")

    @pytest.mark.asyncio
    async def test_legacy_plain_id_accepted(self) -> None:
        assert await _verify_state("762446267") == 762446267

    @pytest.mark.asyncio
    async def test_garbage_rejected(self) -> None:
        with pytest.raises(HTTPException):
            await _verify_state("not-an-id")
