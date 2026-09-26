"""Тесты мониторинга: нормализация апдейтов, счётчики, /metrics (без инфры)."""

import os

os.environ.setdefault("BOT_TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")

from aiogram.types import CallbackQuery, Chat, Message, User

from app.core.metrics import (
    bot_updates_total,
    count_cache,
    describe_update,
    observe_provider,
    render_metrics,
)


def _message(text: str) -> Message:
    user = User(id=1, is_bot=False, first_name="T")
    chat = Chat(id=1, type="private")
    return Message(message_id=1, date=1_700_000_000, chat=chat, from_user=user, text=text)


def test_describe_message_command() -> None:
    assert describe_update(_message("/now")) == ("message", "now")
    assert describe_update(_message("/yandex xxx")) == ("message", "yandex")
    assert describe_update(_message("просто текст")) == ("message", "text")


def test_describe_callback_bounded_cardinality() -> None:
    user = User(id=1, is_bot=False, first_name="T")
    chat = Chat(id=1, type="private")
    msg = Message(message_id=1, date=1_700_000_000, chat=chat, from_user=user, text="x")
    cb = CallbackQuery(
        id="1", from_user=user, chat_instance="i", message=msg, data="svc:toggle:spotify"
    )
    # Только первые два сегмента — хвосты с секретами в лейблы не утекают.
    assert describe_update(cb) == ("callback_query", "svc:toggle")


def test_observe_provider_and_cache_do_not_crash() -> None:
    observe_provider("spotify", 0.01, "ok")
    observe_provider("yandex", 0.02, "error")
    count_cache("hit")
    count_cache("miss")
    assert bot_updates_total.labels("message", "now")._value.get() >= 0


def test_metrics_endpoint_exposes_pms_metrics() -> None:
    from fastapi.testclient import TestClient

    from app.web.app import create_web_app

    client = TestClient(create_web_app())
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    assert "pms_bot_updates_total" in body
    assert "pms_provider_now_playing_total" in body
    assert "pms_circuit_breaker_open" in body


def test_render_metrics_content_type() -> None:
    body, content_type = render_metrics()
    assert isinstance(body, bytes)
    assert "text/plain" in content_type


def test_init_sentry_noop_without_dsn() -> None:
    from app.core.observability import init_sentry

    assert init_sentry() is False