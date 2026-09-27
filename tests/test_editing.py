"""Тесты безопасных правок: 'message is not modified' глушится, остальное летит."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from app.bot.editing import edit_markup_safe, edit_text_safe


def _bad_request(text: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=MagicMock(), message=text)


@pytest.mark.asyncio
async def test_edit_text_ok() -> None:
    message = AsyncMock()
    assert await edit_text_safe(message, "hi") is True
    message.edit_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_edit_text_not_modified_swallowed() -> None:
    message = AsyncMock()
    message.edit_text.side_effect = _bad_request("message is not modified: ...")
    assert await edit_text_safe(message, "hi") is False


@pytest.mark.asyncio
async def test_edit_text_other_errors_reraise() -> None:
    message = AsyncMock()
    message.edit_text.side_effect = _bad_request("message to edit not found")
    with pytest.raises(TelegramBadRequest):
        await edit_text_safe(message, "hi")


@pytest.mark.asyncio
async def test_edit_markup_not_modified_swallowed() -> None:
    message = AsyncMock()
    message.edit_reply_markup.side_effect = _bad_request(
        "Bad Request: message is not modified"
    )
    assert await edit_markup_safe(message, None) is False
