"""Хэндлеры /start, /services, /disconnect — точка входа в мультиаккаунтинг."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.i18n import lang_of, t
from app.bot.keyboards import connect_kb, services_kb
from app.core.redis import invalidate_now_playing_cache
from app.db import repositories as repo
from app.db.models import User
from app.services.spotify import build_authorize_url as sp_auth_url

router = Router()


def _bound_and_active(user: User, integrations: list) -> tuple[set[str], str]:
    return ({i.provider for i in integrations}, user.active_provider or "all")


@router.message(Command("start"))
async def cmd_start(message: Message, session: AsyncSession, db_user: User) -> None:
    lang = lang_of(db_user)
    integrations = await repo.list_integrations(session, db_user.id)
    bound, active = _bound_and_active(db_user, integrations)
    await message.answer(
        t(lang, "start_text"),
        reply_markup=services_kb(bound, active, lang),
    )


@router.message(Command("services"))
async def cmd_services(message: Message, session: AsyncSession, db_user: User) -> None:
    lang = lang_of(db_user)
    integrations = await repo.list_integrations(session, db_user.id)
    bound, active = _bound_and_active(db_user, integrations)
    await message.answer(
        t(lang, "services_text"),
        reply_markup=services_kb(bound, active, lang),
    )


@router.message(Command("disconnect"))
async def cmd_disconnect(
    message: Message, command: CommandObject, session: AsyncSession, db_user: User
) -> None:
    """Отключить сервис: /disconnect spotify|yandex|youtube|lastfm"""
    lang = lang_of(db_user)
    provider = (command.args or "").strip().lower()
    valid_providers = ("spotify", "yandex", "youtube", "lastfm")

    if provider not in valid_providers:
        await message.answer(
            t(lang, "disconnect_usage",
              example=valid_providers[0], available=", ".join(valid_providers))
        )
        return

    integrations = await repo.list_integrations(session, db_user.id)
    bound = {i.provider for i in integrations}

    if provider not in bound:
        await message.answer(t(lang, "disconnect_not_bound", provider=provider.capitalize()))
        return

    await repo.delete_integration(session, db_user.id, provider)
    await repo.log_audit(session, db_user.id, db_user.telegram_id, "disconnect", provider, "command")
    await session.commit()

    # Если отключали активный провайдер — сбрасываем на "all"
    if db_user.active_provider == provider:
        await repo.set_active_provider(session, db_user, "all")
        await session.commit()

    # Инвалидируем кэш now_playing
    await invalidate_now_playing_cache(db_user.telegram_id)

    integrations = await repo.list_integrations(session, db_user.id)
    bound, active = _bound_and_active(db_user, integrations)
    await message.answer(
        t(lang, "disconnect_done", provider=provider.capitalize()),
        reply_markup=services_kb(bound, active, lang),
    )


@router.callback_query(F.data == "svc:back")
async def cb_back(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    lang = lang_of(db_user)
    integrations = await repo.list_integrations(session, db_user.id)
    bound, active = _bound_and_active(db_user, integrations)
    # Сообщение может быть с фото (caption) или текстовым (text)
    if cb.message.photo:
        await cb.message.edit_caption(
            t(lang, "services_title"), reply_markup=services_kb(bound, active, lang)
        )
    else:
        await cb.message.edit_text(
            t(lang, "services_title"), reply_markup=services_kb(bound, active, lang)
        )
    await cb.answer()


@router.callback_query(F.data.startswith("svc:active:"))
async def cb_set_active(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    lang = lang_of(db_user)
    provider = (cb.data or "").split(":")[-1]
    await repo.set_active_provider(session, db_user, provider)
    await session.commit()
    integrations = await repo.list_integrations(session, db_user.id)
    bound, _ = _bound_and_active(db_user, integrations)
    await cb.message.edit_reply_markup(reply_markup=services_kb(bound, provider, lang))
    await cb.answer(t(lang, "set_active_answer", provider=provider.upper()))


@router.callback_query(F.data.startswith("svc:toggle:"))
async def cb_toggle(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    lang = lang_of(db_user)
    provider = (cb.data or "").split(":")[-1]
    integrations = await repo.list_integrations(session, db_user.id)
    bound = {i.provider for i in integrations}

    if provider in bound:
        # Отключаем
        await repo.delete_integration(session, db_user.id, provider)
        await repo.log_audit(
            session, db_user.id, db_user.telegram_id, "disconnect", provider, "button"
        )
        await session.commit()

        # Если отключали активный — сброс на all
        if db_user.active_provider == provider:
            await repo.set_active_provider(session, db_user, "all")
            await session.commit()

        # Инвалидируем кэш
        await invalidate_now_playing_cache(cb.from_user.id)

        await cb.answer(t(lang, "toggle_off_answer", provider=provider))
        integrations = await repo.list_integrations(session, db_user.id)
        bound, active = _bound_and_active(db_user, integrations)
        await cb.message.edit_reply_markup(reply_markup=services_kb(bound, active, lang))
        return

    # Подключаем - используем edit_caption для фото, edit_text для текста
    async def _edit_msg(text: str, markup=None):
        if cb.message.photo:
            return await cb.message.edit_caption(text, reply_markup=markup)
        return await cb.message.edit_text(text, reply_markup=markup)

    if provider == "spotify":
        url = sp_auth_url(state=str(cb.from_user.id))
        await _edit_msg(
            t(lang, "sp_connect"),
            connect_kb(provider, url, lang),
        )
    elif provider == "youtube":
        await _edit_msg(t(lang, "yt_connect"))
    elif provider == "yandex":
        await _edit_msg(t(lang, "yx_connect"))
    elif provider == "lastfm":
        await _edit_msg(t(lang, "lfm_connect"))
    await cb.answer()
