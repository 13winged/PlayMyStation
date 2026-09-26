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


def test_progress_bar_full() -> None:
    bar = progress_bar(180_000, 180_000)
    # При 100% ratio=1.0, filled=12, но HEAD всё равно добавляется
    assert "━" in bar
    assert "●" in bar  # HEAD всегда присутствует


def test_progress_bar_zero() -> None:
    # progress_ms=0 считается falsy, поэтому возвращается пустая строка
    assert progress_bar(0, 180_000) == ""
    # но маленькое положительное значение даёт бар
    bar = progress_bar(1, 180_000)
    assert bar.startswith("<code>●")


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
    assert "Spotify" in card
    assert "Сейчас играет" in card
    assert "Test Song" in card
    assert "Test Artist" in card
    assert "Test Album" in card
    assert "1:00 / 3:00" in card
    assert "Открыть трек" in card


def test_track_card_yandex_not_playing() -> None:
    track = TrackDTO(
        title="Яндекс Трек",
        artist="Яндекс Артист",
        duration_ms=240_000,
        is_playing=False,
        provider="yandex",
    )
    card = track_card(track)
    assert "🔴" in card
    assert "Яндекс Музыка" in card
    assert "Последний трек" in card
    assert "4:00" in card


def test_track_card_duration_without_progress() -> None:
    """Без прогресса — только длительность, без '--:-- /'."""
    track = TrackDTO(
        title="T",
        artist="A",
        duration_ms=158_000,
        progress_ms=None,
        is_playing=False,
        provider="youtube",
    )
    card = track_card(track)
    assert "2:38" in card
    assert "--:--" not in card


def test_track_card_youtube_last_played() -> None:
    track = TrackDTO(
        title="YT Track",
        artist="YT Artist",
        is_playing=False,
        provider="youtube",
    )
    card = track_card(track)
    assert "▶️" in card
    assert "YouTube Music" in card
    assert "Последний трек" in card
    assert "не отдаёт realtime" in card


def test_track_card_without_optional_fields() -> None:
    track = TrackDTO(
        title="Minimal",
        artist="Artist",
        provider="spotify",
    )
    card = track_card(track)
    assert "Minimal" in card
    assert "Artist" in card
    assert "Album" not in card
    assert "--:-- / --:--" not in card  # нет duration


def test_track_card_escapes_html() -> None:
    track = TrackDTO(
        title='Test <provider> & "song"',
        artist="Artist <b>hack</b>",
        album="Album <i>x</i>",
        track_url='https://example.com/track?a=1&b=2"x',
        provider="spotify",
        is_playing=True,
    )
    card = track_card(track)
    assert "<provider>" not in card
    assert "&lt;provider&gt;" in card
    assert "<b>hack</b>" not in card
    assert "&lt;b&gt;hack&lt;/b&gt;" in card