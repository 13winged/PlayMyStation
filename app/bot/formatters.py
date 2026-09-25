"""Форматирование карточки трека: прогресс-бар + иконка провайдера."""

from __future__ import annotations

from app.services.base import TrackDTO

PROVIDER_ICON = {"spotify": "🟢", "yandex": "🔴", "soundcloud": "🟠"}

BAR_LEN = 12
FILLED = "━"
HEAD = "●"
EMPTY = "─"


def progress_bar(progress_ms: int | None, duration_ms: int | None) -> str:
    if not progress_ms or not duration_ms or duration_ms <= 0:
        return ""
    ratio = max(0.0, min(1.0, progress_ms / duration_ms))
    filled = int(ratio * BAR_LEN)
    bar = FILLED * filled + HEAD + EMPTY * (BAR_LEN - filled)
    return f"<code>{bar}</code>"


def fmt_ms(ms: int | None) -> str:
    if ms is None:
        return "--:--"
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


def track_card(track: TrackDTO) -> str:
    icon = PROVIDER_ICON.get(track.provider, "🎵")
    provider_name = {
        "spotify": "Spotify",
        "yandex": "Яндекс Музыка",
        "soundcloud": "SoundCloud",
    }.get(track.provider, track.provider)
    status = "▶️ Сейчас играет" if track.is_playing else "⏸️ Последний трек"
    lines = [
        f"{icon} <b>{provider_name}</b> — {status}",
        f"🎧 <b>{track.title}</b>",
        f"👤 {track.artist}",
    ]
    if track.album:
        lines.append(f"💿 {track.album}")
    if track.duration_ms:
        bar = progress_bar(track.progress_ms, track.duration_ms)
        time = f"{fmt_ms(track.progress_ms)} / {fmt_ms(track.duration_ms)}"
        lines.append(f"{bar} {time}" if bar else time)
    if track.track_url:
        lines.append(f'🔗 <a href="{track.track_url}">Открыть трек</a>')
    elif track.provider == "soundcloud" and not track.is_playing:
        lines.append("ℹ️ SoundCloud не отдаёт realtime-статус — показан последний трек.")
    return "\n".join(lines)
