"""Форматирование карточки трека: прогресс-бар + иконка провайдера."""

from __future__ import annotations

import html

from app.services.base import TrackDTO

PROVIDER_ICON = {"spotify": "🟢", "yandex": "🔴", "youtube": "▶️", "lastfm": "🟪"}

BAR_LEN = 12
HEAD = "●"
EMPTY = "─"


def progress_bar(progress_ms: int | None, duration_ms: int | None) -> str:
    # Тонкий бар с knob'ом как в Spotify; цифры elapsed/-remaining несут инфо.
    if not progress_ms or not duration_ms or duration_ms <= 0:
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


def track_card(track: TrackDTO) -> str:
    """Карточка трека в духе Spotify-плеера.

    Шапка с провайдером (мультиаккаунтинг), жирный тайтл, plain-артист,
    строка времени как в Spotify: elapsed слева, остаток с минусом справа.
    Весь динамический текст экранирован под Telegram HTML.
    """
    icon = PROVIDER_ICON.get(track.provider, "🎵")
    provider_name = html.escape(
        {
            "spotify": "Spotify",
            "yandex": "Яндекс Музыка",
            "youtube": "YouTube Music",
            "lastfm": "Last.fm",
        }.get(track.provider, track.provider),
        quote=False,
    )
    status = "▶️ Сейчас играет" if track.is_playing else "⏸️ Последний трек"
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
        lines.append(f'🔗 <a href="{safe_url}">Открыть трек</a>')
    elif track.provider == "youtube" and not track.is_playing:
        lines.append("ℹ️ YouTube Music не отдаёт realtime-статус — показан последний трек из истории.")
    return "\n".join(lines)
