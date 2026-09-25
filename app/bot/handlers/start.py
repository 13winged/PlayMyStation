"""Хэндлеры /start и /services — точка входа в мультиаккаунтинг."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import connect_kb, services_kb
from app.core.config import get_settings
from app.db import repositories as repo
from app.db.models import User
from app.services.soundcloud import build_authorize_url as sc_auth_url
from app.services.spotify import build_authorize_url as sp_auth_url

router = Router()


def _bound_and_active(user: User, integrations: list) -> tuple[set[str], str]:
    return ({i.provider for i in integrations}, user.active_provider or "all")


@router.message(Command("start"))
async def cmd_start(message: Message, session: AsyncSession, db_user: User) -> None:
    integrations = await repo.list_integrations(session, db_user.id)
    bound, active = _bound_and_active(db_user, integrations)
    await message.answer(
        "👋 <b>PlayMyStation</b>\n\n"
        "Подключи до 3 аккаунтов: Spotify, Яндекс Музыку и SoundCloud.\n"
        "Выбери активный сервис или режим <b>ALL</b> — тогда /now найдёт тот, где музыка играет прямо сейчас.\n\n"
        "Команды:\n"
        "• /services — подключить / выбрать сервис\n"
        "• /now или /np — что сейчас играет",
        reply_markup=services_kb(bound, active),
    )


@router.message(Command("services"))
async def cmd_services(message: Message, session: AsyncSession, db_user: User) -> None:
    integrations = await repo.list_integrations(session, db_user.id)
    bound, active = _bound_and_active(db_user, integrations)
    await message.answer(
        "⚙️ <b>Мои сервисы</b>\nНажми на сервис, чтобы подключить / отключить. "
        "Второй ряд — выбор активного для /now.",
        reply_markup=services_kb(bound, active),
    )


@router.callback_query(F.data == "svc:back")
async def cb_back(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    integrations = await repo.list_integrations(session, db_user.id)
    bound, active = _bound_and_active(db_user, integrations)
    await cb.message.edit_text(
        "⚙️ <b>Мои сервисы</b>", reply_markup=services_kb(bound, active)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("svc:active:"))
async def cb_set_active(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    provider = (cb.data or "").split(":")[-1]
    await repo.set_active_provider(session, db_user, provider)
    await session.commit()
    integrations = await repo.list_integrations(session, db_user.id)
    bound, _ = _bound_and_active(db_user, integrations)
    await cb.message.edit_reply_markup(reply_markup=services_kb(bound, provider))
    await cb.answer(f"Активный сервис: {provider.upper()}")


@router.callback_query(F.data.startswith("svc:toggle:"))
async def cb_toggle(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    provider = (cb.data or "").split(":")[-1]
    integrations = await repo.list_integrations(session, db_user.id)
    bound = {i.provider for i in integrations}
    settings = get_settings()

    if provider in bound:
        # Отключаем
        await repo.delete_integration(session, db_user.id, provider)
        await session.commit()
        await cb.answer(f"{provider} отключён")
        integrations = await repo.list_integrations(session, db_user.id)
        bound, active = _bound_and_active(db_user, integrations)
        await cb.message.edit_reply_markup(reply_markup=services_kb(bound, active))
        return

    # Подключаем
    if provider == "spotify":
        url = sp_auth_url(state=str(cb.from_user.id))
        await cb.message.edit_text(
            "🟢 <b>Подключение Spotify</b>\nНажми кнопку и подтверди доступ.",
            reply_markup=connect_kb(provider, url),
        )
    elif provider == "soundcloud":
        if not settings.soundcloud_client_id:
            await cb.answer("SoundCloud OAuth не настроен (.env)", show_alert=True)
            return
        url = sc_auth_url(state=str(cb.from_user.id))
        await cb.message.edit_text(
            "🟠 <b>Подключение SoundCloud</b>\nНажми кнопку и подтверди доступ.",
            reply_markup=connect_kb(provider, url),
        )
    elif provider == "yandex":
        await cb.message.edit_text(
            "🔴 <b>Подключение Яндекс Музыки</b>\n\n"
            "1. Открой relay: <code>https://yandex-music-auth.vercel.app</code> (или получи токен любым способом)\n"
            "2. Скопируй OAuth-токен Яндекса\n"
            "3. Отправь его следующим сообщением с командой:\n"
            "<code>/yandex &lt;токен&gt;</code>\n\n"
            "Токен хранится в зашифрованном виде и используется только для чтения очереди."
        )
    await cb.answer()
