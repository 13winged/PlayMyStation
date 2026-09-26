"""Хэндлеры /start, /services, /disconnect — точка входа в мультиаккаунтинг."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

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
    integrations = await repo.list_integrations(session, db_user.id)
    bound, active = _bound_and_active(db_user, integrations)
    await message.answer(
        "👋 <b>PlayMyStation</b>\n\n"
        "Подключи до 4 аккаунтов: Spotify, Яндекс Музыку, YouTube Music и Last.fm.\n"
        "Выбери активный сервис или режим <b>ALL</b> — тогда /now найдёт тот, где музыка играет прямо сейчас.\n\n"
        "Команды:\n"
        "• /services — подключить / выбрать сервис\n"
        "• /now или /np — что сейчас играет (+ пришлю трек)\n"
        "• /spotify /yandex /youtube /lastfm — подключить конкретный сервис\n"
        "• /disconnect <provider> — отключить сервис",
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


@router.message(Command("disconnect"))
async def cmd_disconnect(
    message: Message, command: CommandObject, session: AsyncSession, db_user: User
) -> None:
    """Отключить сервис: /disconnect spotify|yandex|youtube|lastfm"""
    provider = (command.args or "").strip().lower()
    valid_providers = ("spotify", "yandex", "youtube", "lastfm")

    if provider not in valid_providers:
        await message.answer(
            f"❌ Укажи провайдера: <code>/disconnect {valid_providers[0]}</code>\n"
            f"Доступные: {', '.join(valid_providers)}"
        )
        return

    integrations = await repo.list_integrations(session, db_user.id)
    bound = {i.provider for i in integrations}

    if provider not in bound:
        await message.answer(f"ℹ️ {provider.capitalize()} не был подключен.")
        return

    await repo.delete_integration(session, db_user.id, provider)
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
        f"✅ {provider.capitalize()} отключён.",
        reply_markup=services_kb(bound, active),
    )


@router.callback_query(F.data == "svc:back")
async def cb_back(cb: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    integrations = await repo.list_integrations(session, db_user.id)
    bound, active = _bound_and_active(db_user, integrations)
    # Сообщение может быть с фото (caption) или текстовым (text)
    if cb.message.photo:
        await cb.message.edit_caption("⚙️ <b>Мои сервисы</b>", reply_markup=services_kb(bound, active))
    else:
        await cb.message.edit_text("⚙️ <b>Мои сервисы</b>", reply_markup=services_kb(bound, active))
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

    if provider in bound:
        # Отключаем
        await repo.delete_integration(session, db_user.id, provider)
        await session.commit()

        # Если отключали активный — сброс на all
        if db_user.active_provider == provider:
            await repo.set_active_provider(session, db_user, "all")
            await session.commit()

        # Инвалидируем кэш
        await invalidate_now_playing_cache(cb.from_user.id)

        await cb.answer(f"{provider} отключён")
        integrations = await repo.list_integrations(session, db_user.id)
        bound, active = _bound_and_active(db_user, integrations)
        await cb.message.edit_reply_markup(reply_markup=services_kb(bound, active))
        return

    # Подключаем - используем edit_caption для фото, edit_text для текста
    async def _edit_msg(text: str, markup=None):
        if cb.message.photo:
            return await cb.message.edit_caption(text, reply_markup=markup)
        return await cb.message.edit_text(text, reply_markup=markup)

    if provider == "spotify":
        url = sp_auth_url(state=str(cb.from_user.id))
        await _edit_msg(
            "🟢 <b>Подключение Spotify</b>\nНажми кнопку и подтверди доступ.\n\n"
            "Если страница колбэка не откроется — скопируй параметр "
            "<code>code=...</code> из адресной строки и пришли командой "
            "<code>/spotify <код></code>.",
            connect_kb(provider, url),
        )
    elif provider == "youtube":
        await _edit_msg(
            "▶️ <b>Подключение YouTube Music</b>\n\n"
            "1. Открой <code>music.youtube.com</code> в браузере и войди в аккаунт\n"
            "2. Открой DevTools (Ctrl+Shift+I) → Network, в фильтр введи "
            "<code>/browse</code>\n"
            "3. Обнови страницу, найди POST-запрос <code>browse?...</code> и скопируй "
            "заголовки ЦЕЛИКОМ (включая <code>authorization:</code>, "
            "<code>cookie:</code> и <code>x-goog-authuser:</code>)\n"
            "4. Пришли их боту командой:\n"
            "<code>/youtube &lt;заголовки&gt;</code>"
        )
    elif provider == "yandex":
        await _edit_msg(
            "🔴 <b>Подключение Яндекс Музыки</b>\n\n"
            "1. Открой ссылку и войди в свой Яндекс ID:\n"
            "<code>https://oauth.yandex.ru/authorize?response_type=token&client_id=23cabbbdc6cd418abb4b39c32c41195d</code>\n"
            "2. После входа тебя вернёт на music.yandex.ru — скопируй "
            "значение <code>access_token=...</code> из адресной строки\n"
            "3. Пришли его боту командой:\n"
            "<code>/yandex <токен></code>\n\n"
            "Токен хранится в зашифрованном виде и используется только для чтения очереди."
        )
    elif provider == "lastfm":
        await _edit_msg(
            "🟪 <b>Подключение Last.fm</b>\n\n"
            "OAuth не нужен — просто пришли свой username:\n"
            "<code>/lastfm <username></code>\n\n"
            "Чтобы бот видел треки из Spotify, свяжи Spotify → Last.fm "
            "(скробблинг) в настройках Last.fm. Работает и на free-аккаунтах."
        )
    await cb.answer()