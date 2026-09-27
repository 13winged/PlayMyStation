"""Форматирование карточки трека: прогресс-бар + иконка провайдера."""

from __future__ import annotations

import html

from app.bot.i18n import t
from app.services.base import TrackDTO

PROVIDER_ICON = {"spotify": "🟢", "yandex": "🔴", "youtube": "▶️", "lastfm": "🟪"}

BAR_LEN = 12
HEAD = "●"
EMPTY = "─"


def progress_bar(progress_ms: int | None, duration_ms: int | None) -> str:
    # Тонкий бар с knob'ом как в Spotify; цифры elapsed/-remaining несут инфо.
    if progress_ms is None or not duration_ms or duration_ms <= 0:
        return ""
    ratio = max(0.0, min(1.0, progress_ms / duration_ms))
    filled = int(ratio * BAR_LEN)
    bar = EMPTY * filled + HEAD + EMPTY * (BAR_LEN - filled)
    return f"<code>{bar}</code>"


def fmt_ms(ms: int | None) -> str:
    if ms is None:
        return "--:--"
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


def track_card(track: TrackDTO, lang: str = "ru") -> str:
    """Карточка трека в духе Spotify-плеера.

    Шапка с провайдером (мультиаккаунтинг), жирный тайтл, plain-артист,
    строка времени как в Spotify: elapsed слева, остаток с минусом справа.
    Весь динамический текст экранирован под Telegram HTML.
    """
    icon = PROVIDER_ICON.get(track.provider, "🎵")
    provider_name = html.escape(
        {
            "spotify": t(lang, "provider_spotify"),
            "yandex": t(lang, "provider_yandex"),
            "youtube": t(lang, "provider_youtube"),
            "lastfm": t(lang, "provider_lastfm"),
        }.get(track.provider, track.provider),
        quote=False,
    )
    status = t(lang, "card_playing") if track.is_playing else t(lang, "card_paused")
    title = html.escape(track.title, quote=False)
    artist = html.escape(track.artist, quote=False)
    lines = [
        f"{icon} <b>{provider_name}</b> — {status}",
        f"<b>{title}</b>",
        artist,
    ]
    if track.album:
        lines.append(f"💿 {html.escape(track.album, quote=False)}")
    if track.duration_ms:
        if track.progress_ms:
            bar = progress_bar(track.progress_ms, track.duration_ms)
            remaining = max(0, track.duration_ms - track.progress_ms)
            time = f"{fmt_ms(track.progress_ms)} {bar} -{fmt_ms(remaining)}"
        else:
            time = fmt_ms(track.duration_ms)  # прогресса нет — только длительность
        lines.append(time)
    if track.track_url:
        safe_url = html.escape(track.track_url, quote=True)
        lines.append(f'🔗 <a href="{safe_url}">{t(lang, "card_open_track")}</a>')
    elif track.provider == "youtube" and not track.is_playing:
        lines.append(t(lang, "card_yt_note"))
    return "\n".join(lines)
