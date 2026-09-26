"""Тесты song.link-матчинга: парсинг ответа, фильтры, клавиатура (без сети)."""

from app.bot.keyboards import track_kb
from app.services.songlink import parse_links, source_supported


def _api_response() -> dict:
    return {
        "linksByPlatform": {
            "spotify": {"url": "https://open.spotify.com/track/abc"},
            "yandex": {"url": "https://music.yandex.ru/track/123"},
            "youtube": {"url": "https://music.youtube.com/watch?v=xyz"},
            "appleMusic": {"url": "https://music.apple.com/us/song/x"},
        }
    }


def test_parse_links_order_and_content() -> None:
    links = parse_links(_api_response())
    assert list(links) == ["spotify", "yandex", "youtube"]  # apple — не показываем
    assert links["spotify"] == "https://open.spotify.com/track/abc"


def test_parse_links_excludes_current_provider() -> None:
    links = parse_links(_api_response(), exclude=("spotify",))
    assert "spotify" not in links
    assert "yandex" in links


def test_parse_links_garbage() -> None:
    assert parse_links({}) == {}
    assert parse_links({"linksByPlatform": None}) == {}
    assert parse_links({"linksByPlatform": {"spotify": {}}}) == {}


def test_source_supported() -> None:
    assert source_supported("https://open.spotify.com/track/abc")
    assert source_supported("https://music.yandex.ru/album/1/track/2")
    assert source_supported("https://music.youtube.com/watch?v=xyz")
    assert source_supported("https://youtu.be/xyz")
    assert not source_supported("https://www.last.fm/music/A/_/T")
    assert not source_supported("")


def test_track_kb_with_platform_links() -> None:
    kb = track_kb(False, {"spotify": "https://open.spotify.com/track/abc"})
    rows = kb.inline_keyboard
    assert len(rows) == 2  # платформы + сервисы
    btn = rows[0][0]
    assert btn.url == "https://open.spotify.com/track/abc"
    assert "Spotify" in (btn.text or "")


def test_track_kb_without_links_unchanged() -> None:
    kb = track_kb(False, None)
    assert len(kb.inline_keyboard) == 1  # только сервисы
    kb_preview = track_kb(True, {})
    assert len(kb_preview.inline_keyboard) == 2  # превью + сервисы
