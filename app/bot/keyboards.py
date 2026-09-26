"""Inline-клавиатуры: статусы привязки + выбор активного сервиса."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

PROVIDER_META: dict[str, tuple[str, str]] = {
    "spotify": ("Spotify", "🟢"),
    "yandex": ("Яндекс Музыка", "🔴"),
    "youtube": ("YouTube Music", "▶️"),
    "lastfm": ("Last.fm", "🟪"),
}


def services_kb(bound: set[str], active: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    status_row: list[InlineKeyboardButton] = []
    for provider, (label, _emoji) in PROVIDER_META.items():
        mark = "✅" if provider in bound else "➕"
        status_row.append(
            InlineKeyboardButton(text=f"{mark} {label}", callback_data=f"svc:toggle:{provider}")
        )
    rows.append(status_row)

    active_row = [
        InlineKeyboardButton(
            text=("🔹 ALL" if active == "all" else "ALL"),
            callback_data="svc:active:all",
        )
    ]
    for provider, (label, _emoji) in PROVIDER_META.items():
        prefix = "🔹 " if active == provider else ""
        active_row.append(
            InlineKeyboardButton(text=f"{prefix}{label}", callback_data=f"svc:active:{provider}")
        )
    # Разбиваем: первая строка — статусы, далее по 2 кнопки активного
    rows.append(active_row[:2])
    rows.append(active_row[2:])
    rows.append([InlineKeyboardButton(text="🎵 Сейчас играет (/now)", callback_data="svc:now")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def connect_kb(provider: str, auth_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Подключить", url=auth_url)],
            [InlineKeyboardButton(text="◀️ Назад к сервисам", callback_data="svc:back")],
        ]
    )


def now_empty_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Мои сервисы", callback_data="svc:back")],
        ]
    )


def track_kb(has_preview: bool, platform_links: dict[str, str] | None = None) -> InlineKeyboardMarkup:
    """Клавиатура под карточкой трека: превью + другие платформы + сервисы."""
    rows: list[list[InlineKeyboardButton]] = []
    if has_preview:
        rows.append(
            [InlineKeyboardButton(text="⏬ Превью (30 сек)", callback_data="dl:preview")]
        )
    if platform_links:
        buttons = [
            InlineKeyboardButton(text=f"{PROVIDER_META[p][1]} {PROVIDER_META[p][0]}", url=url)
            for p, url in platform_links.items()
            if p in PROVIDER_META
        ]
        if buttons:
            rows.append(buttons)
    rows.append([InlineKeyboardButton(text="⚙️ Мои сервисы", callback_data="svc:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
