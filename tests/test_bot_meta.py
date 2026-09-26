"""Тесты меню команд и описания бота: лимиты Telegram + вызовы API."""

import re
from unittest.mock import AsyncMock

import pytest

from app.bot.commands import (
    BOT_COMMANDS,
    BOT_DESCRIPTION,
    BOT_SHORT_DESCRIPTION,
    setup_bot_meta,
)


def test_commands_valid() -> None:
    assert len(BOT_COMMANDS) >= 10
    names = [c.command for c in BOT_COMMANDS]
    assert len(set(names)) == len(names)  # без дублей
    for c in BOT_COMMANDS:
        assert re.fullmatch(r"[a-z0-9_]{1,32}", c.command), c.command
        assert 1 <= len(c.description) <= 256, c.command


def test_commands_cover_all_handlers() -> None:
    names = {c.command for c in BOT_COMMANDS}
    for expected in ("start", "services", "now", "np", "spotify", "yandex",
                     "youtube", "lastfm", "lang", "disconnect"):
        assert expected in names


def test_descriptions_within_telegram_limits() -> None:
    assert 1 <= len(BOT_SHORT_DESCRIPTION) <= 120
    assert 1 <= len(BOT_DESCRIPTION) <= 512


@pytest.mark.asyncio
async def test_setup_bot_meta_calls_api() -> None:
    bot = AsyncMock()
    await setup_bot_meta(bot)
    bot.set_my_commands.assert_awaited_once_with(BOT_COMMANDS)
    bot.set_my_short_description.assert_awaited_once_with(BOT_SHORT_DESCRIPTION)
    bot.set_my_description.assert_awaited_once_with(BOT_DESCRIPTION)


@pytest.mark.asyncio
async def test_setup_bot_meta_best_effort_on_api_error() -> None:
    bot = AsyncMock()
    bot.set_my_commands.side_effect = RuntimeError("no network")
    await setup_bot_meta(bot)  # не бросает
