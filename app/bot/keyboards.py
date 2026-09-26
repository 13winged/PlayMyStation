"""Inline-клавиатуры: статусы привязки + выбор активного сервиса."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.i18n import t

PROVIDER_META: dict[str, tuple[str, str]] = {
    "spotify": ("Spotify", "🟢"),
    "yandex": ("Яндекс Музыка", "🔴"),
    "youtube": ("YouTube Music", "▶️"),
    "lastfm": ("Last.fm", "🟪"),
}

PROVIDER_META_EN: dict[str, tuple[str, str]] = {
    "spotify": ("Spotify", "🟢"),
    "yandex": ("Yandex Music", "🔴"),
    "youtube": ("YouTube Music", "▶️"),
    "lastfm": ("Last.fm", "🟪"),
}


def _meta(lang: str) -> dict[str, tuple[str, str]]:
    return PROVIDER_META_EN if lang == "en" else PROVIDER_META


def services_kb(bound: set[str], active: str, lang: str = "ru") -> InlineKeyboardMarkup:
    meta = _meta(lang)
    rows: list[list[InlineKeyboardButton]] = []
    status_row: list[InlineKeyboardButton] = []
    for provider, (label, _emoji) in meta.items():
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
    for provider, (label, _emoji) in meta.items():
        prefix = "🔹 " if active == provider else ""
        active_row.append(
            InlineKeyboardButton(text=f"{prefix}{label}", callback_data=f"svc:active:{provider}")
        )
    # Разбиваем: первая строка — статусы, далее по 2 кнопки активного
    rows.append(active_row[:2])
    rows.append(active_row[2:])
    rows.append([InlineKeyboardButton(text=t(lang, "btn_now"), callback_data="svc:now")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def connect_kb(provider: str, auth_url: str, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "btn_connect"), url=auth_url)],
            [InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="svc:back")],
        ]
    )


def now_empty_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "btn_services"), callback_data="svc:back")],
        ]
    )


def track_kb(
    has_preview: bool,
    platform_links: dict[str, str] | None = None,
    lang: str = "ru",
    controls: bool = False,
    playing: bool = False,
) -> InlineKeyboardMarkup:
    """Клавиатура под карточкой: превью + управление + платформы + сервисы."""
    meta = _meta(lang)
    rows: list[list[InlineKeyboardButton]] = []
    if has_preview:
        rows.append(
            [InlineKeyboardButton(text=t(lang, "btn_preview"), callback_data="dl:preview")]
        )
    if controls:
        toggle = t(lang, "btn_pause") if playing else t(lang, "btn_play")
        rows.append(
            [
                InlineKeyboardButton(text=toggle, callback_data="ctl:toggle"),
                InlineKeyboardButton(text=t(lang, "btn_prev"), callback_data="ctl:prev"),
                InlineKeyboardButton(text=t(lang, "btn_next"), callback_data="ctl:next"),
                InlineKeyboardButton(text=t(lang, "btn_like"), callback_data="ctl:like"),
            ]
        )
    if platform_links:
        buttons = [
            InlineKeyboardButton(text=f"{meta[p][1]} {meta[p][0]}", url=url)
            for p, url in platform_links.items()
            if p in meta
        ]
        if buttons:
            rows.append(buttons)
    rows.append([InlineKeyboardButton(text=t(lang, "btn_services"), callback_data="svc:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
