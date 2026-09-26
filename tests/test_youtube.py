"""Тесты валидации YouTube Music auth-JSON (без ytmusicapi — чистая функция)."""

import json

import pytest

from app.services.youtube import validate_auth_json


def _auth_json(**overrides: object) -> str:
    base: dict[str, object] = {
        "authorization": "SAPISIDHASH 123_abc",
        "cookie": "SID=aaa; __Secure-3PAPISID=bbb; HSID=ccc",
        "x-goog-authuser": "0",
    }
    base.update(overrides)
    return json.dumps(base)


def test_validate_auth_json_ok() -> None:
    validate_auth_json(_auth_json())  # не бросает


def test_validate_auth_json_missing_authorization() -> None:
    data = json.loads(_auth_json())
    del data["authorization"]
    with pytest.raises(ValueError, match="missing headers"):
        validate_auth_json(json.dumps(data))


def test_validate_auth_json_guest_session_no_3papisid() -> None:
    """Гостевая сессия (нет __Secure-3PAPISID) — отклоняем до сохранения."""
    with pytest.raises(ValueError, match="3PAPISID"):
        validate_auth_json(_auth_json(cookie="YSC=xyz; SIDCC=aaa; PREF=bbb"))


def test_validate_auth_json_not_json() -> None:
    with pytest.raises(ValueError, match="not JSON"):
        validate_auth_json("cookie: blah")
    with pytest.raises(TypeError, match="not JSON"):
        validate_auth_json("[1, 2]")
