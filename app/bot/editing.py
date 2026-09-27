"""Безопасные правки сообщений: игнор 'message is not modified'.

Повторный тап по инлайн-кнопке правит разметку на идентичную —
Telegram отвечает 400. Без глушилки это превращается в 500 на вебхуке
и Telegram начинает ретраить апдейт (дубли обработки).
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

log = logging.getLogger("playmystation.editing")


def _is_not_modified(e: TelegramBadRequest) -> bool:
    return "message is not modified" in str(e).lower()


async def edit_text_safe(message: Message, text: str, **kwargs: Any) -> bool:
    """edit_text, False если править было нечего. Остальные ошибки — наружу."""
    try:
        await message.edit_text(text, **kwargs)
        return True
    except TelegramBadRequest as e:
        if _is_not_modified(e):
            return False
        raise


async def edit_caption_safe(message: Message, caption: str, **kwargs: Any) -> bool:
    try:
        await message.edit_caption(caption, **kwargs)
        return True
    except TelegramBadRequest as e:
        if _is_not_modified(e):
            return False
        raise


async def edit_markup_safe(
    message_or_cb: Message | CallbackQuery, markup: InlineKeyboardMarkup | None
) -> bool:
    """edit_reply_markup для Message или CallbackQuery.message."""
    message = message_or_cb.message if isinstance(message_or_cb, CallbackQuery) else message_or_cb
    try:
        await message.edit_reply_markup(reply_markup=markup)
        return True
    except TelegramBadRequest as e:
        if _is_not_modified(e):
            return False
        raise
