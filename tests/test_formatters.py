"""Smoke-тесты форматирования карточки трека (без внешних зависимостей)."""

from app.bot.formatters import fmt_ms, progress_bar, track_card
from app.services.base import TrackDTO


def test_fmt_ms() -> None:
    assert fmt_ms(0) == "0:00"
    assert fmt_ms(65_000) == "1:05"
    assert fmt_ms(None) == "--:--"


def test_progress_bar_half() -> None:
    bar = progress_bar(90_000, 180_000)
    assert "●" in bar


def test_progress_bar_empty_without_times() -> None:
    assert progress_bar(None, 180_000) == ""
    assert progress_bar(90_000, None) == ""


def test_track_card_spotify() -> None:
    track = TrackDTO(
        title="Test Song",
        artist="Test Artist",
        album="Test Album",
        duration_ms=180_000,
        progress_ms=60_000,
        is_playing=True,
        track_url="https://open.spotify.com/track/abc",
        provider="spotify",
    )
    card = track_card(track)
    assert "🟢" in card
    assert "Test Song" in card
    assert "1:00 / 3:00" in card
    assert "Открыть трек" in card
