"""Тесты скачивания превью и YouTube Music-маппинга истории."""

from app.services.audio import safe_filename
from app.services.youtube import YouTubeMusicService


def test_safe_filename_strips_forbidden_chars() -> None:
    name = safe_filename('Art<ist>', 'Tit/le: "X"?*')
    assert "<" not in name
    assert ">" not in name
    assert "/" not in name
    assert name.endswith(".mp3")


def test_safe_filename_fallback_for_empty() -> None:
    assert safe_filename("", "") == "track.mp3"


def test_safe_filename_truncates_long_names() -> None:
    name = safe_filename("A" * 100, "B" * 100)
    assert len(name) <= 64  # 60 символов базы + .mp3
    assert name.endswith(".mp3")


def test_youtube_dto_full_history_item() -> None:
    """Полный item истории маппится в TrackDTO."""
    raw = {
        "videoId": "dQw4w9WgXcQ",
        "title": "Never Gonna Give You Up",
        "artists": [{"name": "Rick Astley", "id": "UCuAXFkgpKOUHtEU4457amMuo"}],
        "album": {"name": "Whenever You Need Somebody", "id": "MPREb_123"},
        "duration_seconds": 213,
        "thumbnails": [
            {"url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg", "width": 120, "height": 90},
            {"url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg", "width": 480, "height": 360},
        ],
    }
    dto = YouTubeMusicService._to_dto(raw)
    assert dto.title == "Never Gonna Give You Up"
    assert dto.artist == "Rick Astley"
    assert dto.album == "Whenever You Need Somebody"
    assert dto.duration_ms == 213_000
    assert dto.is_playing is False
    assert dto.provider == "youtube"
    assert dto.preview_url is None
    assert dto.track_url == "https://music.youtube.com/watch?v=dQw4w9WgXcQ"
    assert dto.cover_url == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"


def test_youtube_dto_multiple_artists_and_missing_fields() -> None:
    """Несколько артистов склеиваются; пустой item даёт дефолты."""
    raw = {
        "videoId": "abc123",
        "title": "Collab",
        "artists": [{"name": "A"}, {"name": "B"}],
    }
    dto = YouTubeMusicService._to_dto(raw)
    assert dto.artist == "A, B"
    assert dto.album is None
    assert dto.duration_ms is None
    assert dto.cover_url is None

    dto_empty = YouTubeMusicService._to_dto({})
    assert dto_empty.title == "Unknown title"
    assert dto_empty.artist == "Unknown artist"
    assert dto_empty.track_url is None


def test_youtube_dto_filters_view_counts_from_artists() -> None:
    """Счётчик просмотров в artists (особенность истории YT для видео) вычищается."""
    raw = {
        "videoId": "xyz",
        "title": "Pretty Boy (feat. Lil Yachty)",
        "artists": [{"name": "Joji"}, {"name": "29M views"}],
    }
    dto = YouTubeMusicService._to_dto(raw)
    assert dto.artist == "Joji"


def test_extract_code_bare() -> None:
    from app.bot.handlers.spotify_auth import extract_code_and_state

    code, state = extract_code_and_state("AQAxrc3Te9e57T9mRB_nNMSscZdz1")
    assert code == "AQAxrc3Te9e57T9mRB_nNMSscZdz1"
    assert state is None


def test_extract_code_with_state_tail() -> None:
    """Код с хвостом &state=... — хвост отрезается, state извлекается."""
    from app.bot.handlers.spotify_auth import extract_code_and_state

    code, state = extract_code_and_state("AQAxrc3Te9e57&state=762446267")
    assert code == "AQAxrc3Te9e57"
    assert state == "762446267"


def test_extract_code_full_url() -> None:
    from app.bot.handlers.spotify_auth import extract_code_and_state

    url = "https://hissihyss2.com/oauth/spotify/callback?code=AQAxrc3&state=762446267"
    code, state = extract_code_and_state(url)
    assert code == "AQAxrc3"
    assert state == "762446267"


def test_extract_yandex_token_variants() -> None:
    from app.bot.handlers.yandex_auth import extract_yandex_token

    assert extract_yandex_token("y0_abc123") == "y0_abc123"
    assert extract_yandex_token("y0_abc123&token_type=bearer&expires_in=1") == "y0_abc123"
    assert (
        extract_yandex_token("https://music.yandex.ru/#access_token=y0_abc123&token_type=bearer")
        == "y0_abc123"
    )
    assert extract_yandex_token("") == ""
