"""Тесты make_yandex_client: прокси пробрасывается, без него — напрямую."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.yandex import make_yandex_client


@pytest.fixture
def stub_yandex_music(monkeypatch):
    created: dict = {}
    mod = types.ModuleType("yandex_music")
    utils_mod = types.ModuleType("yandex_music.utils")
    req_mod = types.ModuleType("yandex_music.utils.request")

    class FakeRequest:
        def __init__(self, **kwargs):
            created["request_kwargs"] = kwargs

    class FakeClient:
        def __init__(self, token, **kwargs):
            created["token"] = token
            created["kwargs"] = kwargs

        def init(self):
            created["inited"] = True
            return self

    mod.Client = FakeClient
    req_mod.Request = FakeRequest
    monkeypatch.setitem(sys.modules, "yandex_music", mod)
    monkeypatch.setitem(sys.modules, "yandex_music.utils", utils_mod)
    monkeypatch.setitem(sys.modules, "yandex_music.utils.request", req_mod)
    return created


def _patch_proxy(url: str):
    settings = SimpleNamespace(yandex_proxy_url=url)
    return patch("app.core.config.get_settings", return_value=settings)


def test_make_client_with_proxy(stub_yandex_music) -> None:
    with _patch_proxy("http://user:pass@proxy:8080"):
        client = make_yandex_client("tok")
    assert stub_yandex_music["token"] == "tok"
    assert stub_yandex_music["request_kwargs"] == {"proxy_url": "http://user:pass@proxy:8080"}
    assert "request" in stub_yandex_music["kwargs"]
    assert stub_yandex_music["inited"] is True
    assert client is not None


def test_make_client_without_proxy(stub_yandex_music) -> None:
    with _patch_proxy(""):
        make_yandex_client("tok")
    assert stub_yandex_music["token"] == "tok"
    assert stub_yandex_music["kwargs"] == {}
    assert "request_kwargs" not in stub_yandex_music
