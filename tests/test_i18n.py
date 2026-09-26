"""Тесты локализации: паритет ключей, плейсхолдеры, фолбэк."""

import re
from types import SimpleNamespace

from app.bot.i18n import STRINGS, lang_of, t


def _placeholders(template: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", template))


def test_key_parity_ru_en() -> None:
    assert set(STRINGS["ru"]) == set(STRINGS["en"])


def test_placeholders_match_between_langs() -> None:
    for key in STRINGS["ru"]:
        assert _placeholders(STRINGS["ru"][key]) == _placeholders(STRINGS["en"][key]), key


def test_no_unrendered_html_entities_in_placeholders() -> None:
    # Плейсхолдеры вида {x} не должны быть заэкранированы в шаблонах.
    for lang in ("ru", "en"):
        for key, template in STRINGS[lang].items():
            assert "&#" not in template, (lang, key)


def test_t_formats_and_falls_back() -> None:
    assert t("en", "sp_ok") == "✅ Spotify connected! Hit /now 🎵"
    assert t("ru", "sp_ok") == "✅ Spotify подключён! Жми /now 🎵"
    assert "762446267" in t("en", "sp_wrong_state", state="762446267")
    assert t("xx", "sp_ok") == t("ru", "sp_ok")  # неизвестный язык → RU


def test_lang_of() -> None:
    assert lang_of(SimpleNamespace(language="en")) == "en"
    assert lang_of(SimpleNamespace(language="ru")) == "ru"
    assert lang_of(SimpleNamespace(language="de")) == "ru"
    assert lang_of(SimpleNamespace(language=None)) == "ru"
    assert lang_of(None) == "ru"


def test_card_renders_in_english() -> None:
    from app.bot.formatters import track_card
    from app.services.base import TrackDTO

    card = track_card(
        TrackDTO(title="T", artist="A", provider="yandex", is_playing=True), lang="en"
    )
    assert "Yandex Music" in card
    assert "Now playing" in card


def test_keyboards_render_in_english() -> None:
    from app.bot.keyboards import now_empty_kb, services_kb, track_kb

    kb = services_kb(set(), "all", "en")
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Now playing (/now)" in (x or "") for x in texts)
    assert any("Yandex Music" in (x or "") for x in texts)
    assert track_kb(True, None, "en").inline_keyboard[0][0].text == "⏬ Preview (30 sec)"
    assert now_empty_kb("en").inline_keyboard[0][0].text == "⚙️ My services"
