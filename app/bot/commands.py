"""Меню команд и описание бота.

Выставляется через Bot API при каждом старте (см. setup_bot_meta) —
так меню версионируется в git, а не настраивается руками в BotFather.
Лимиты Telegram: команда 1–32 [a-z0-9_], описание команды 1–256 символов,
короткое описание ≤120, полное ≤512.
"""

from __future__ import annotations

import logging

from aiogram.types import BotCommand

log = logging.getLogger("playmystation.bot_meta")

BOT_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Запустить бота и показать сервисы"),
    BotCommand(command="services", description="Подключить и выбрать сервис"),
    BotCommand(command="now", description="Что сейчас играет (+ пришлю трек)"),
    BotCommand(command="np", description="Короткое /now"),
    BotCommand(command="spotify", description="Spotify: выбрать / подключить"),
    BotCommand(command="yandex", description="Яндекс: выбрать / подключить"),
    BotCommand(command="youtube", description="YouTube: выбрать / подключить"),
    BotCommand(command="lastfm", description="Last.fm: выбрать / подключить"),
    BotCommand(command="disconnect", description="Отключить сервис"),
]

BOT_SHORT_DESCRIPTION = "Spotify, Яндекс, YouTube и Last.fm — что играет сейчас"

BOT_DESCRIPTION = (
    "PlayMyStation показывает, что у тебя играет прямо сейчас.\n\n"
    "Подключи до 4 аккаунтов: Spotify, Яндекс Музыку, YouTube Music "
    "и Last.fm. Команда /now найдёт активный сервис (или все сразу "
    "в режиме ALL) и пришлёт карточку трека с аудио.\n\n"
    "Начни с /services."
)


async def setup_bot_meta(bot) -> None:  # type: ignore[no-untyped-def]
    """Выставить меню команд и описание. Best-effort — бот работает и без них."""
    try:
        await bot.set_my_commands(BOT_COMMANDS)
        await bot.set_my_short_description(BOT_SHORT_DESCRIPTION)
        await bot.set_my_description(BOT_DESCRIPTION)
    except Exception:
        log.warning("setup_bot_meta failed", exc_info=True)
