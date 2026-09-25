"""Тесты скачивания превью и SoundCloud-маппинга download_url."""

from app.services.audio import safe_filename
from app.services.soundcloud import SoundCloudService


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


def test_soundcloud_dto_with_downloadable() -> None:
    """download_url пробрасывается только если автор разрешил скачивание."""
    raw = {
        "title": "Track",
        "user": {"username": "Artist"},
        "permalink_url": "https://soundcloud.com/a/t",
        "downloadable": True,
        "download_url": "https://api.soundcloud.com/tracks/1/download",
    }
    dto = SoundCloudService._to_dto(raw, is_playing=False)
    assert dto.preview_url == "https://api.soundcloud.com/tracks/1/download"


def test_soundcloud_dto_without_downloadable() -> None:
    """Без флага downloadable качать нельзя — preview_url None."""
    raw = {
        "title": "Track",
        "user": {"username": "Artist"},
        "permalink_url": "https://soundcloud.com/a/t",
        "downloadable": False,
        "download_url": "https://api.soundcloud.com/tracks/1/download",
    }
    dto = SoundCloudService._to_dto(raw, is_playing=False)
    assert dto.preview_url is None


def test_soundcloud_dto_missing_download_fields() -> None:
    raw = {"title": "Track", "user": {"username": "Artist"}}
    dto = SoundCloudService._to_dto(raw, is_playing=False)
    assert dto.preview_url is None
