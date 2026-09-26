"""Переключение языка RU/EN через /lang."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.i18n import lang_of, t
from app.db import repositories as repo
from app.db.models import User

router = Router()


def lang_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
            ]
        ]
    )


@router.message(Command("lang"))
async def cmd_lang(message: Message, session: AsyncSession, db_user: User) -> None:
    lang = lang_of(db_user)
    current = t(lang, "lang_name_ru") if lang == "ru" else t(lang, "lang_name_en")
    await message.answer(t(lang, "lang_current", lang=current), reply_markup=lang_kb())


@router.callback_query(F.data.startswith("lang:"))
async def cb_lang(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    new_lang = (cb.data or "").split(":")[-1]
    if new_lang not in ("ru", "en"):
        await cb.answer()
        return
    await repo.set_language(session, db_user, new_lang)
    await session.commit()
    # Отвечаем уже на новом языке, клавиатуру убираем.
    await cb.message.edit_text(t(new_lang, "lang_set", lang=new_lang.upper()))
    await cb.answer()
