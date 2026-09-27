"""Тесты валидации YouTube Music auth-JSON (без ytmusicapi — чистая функция)."""

import json

import pytest

from app.services.youtube import (
    cookie_header_to_netscape,
    extract_cookie,
    normalize_headers_raw,
    validate_auth_json,
)


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


def test_normalize_headers_raw_joins_split_value() -> None:
    raw = "authorization: \nSAPISIDHASH abc_u\ncookie: SID=x\nx-goog-authuser: 0"
    out = normalize_headers_raw(raw)
    assert "authorization: SAPISIDHASH abc_u" in out.splitlines()


def test_normalize_headers_raw_keeps_single_lines() -> None:
    raw = "authorization: SAPISIDHASH abc_u\ncookie: SID=x"
    assert normalize_headers_raw(raw) == raw


def test_normalize_headers_raw_skips_blanks() -> None:
    assert normalize_headers_raw("\ncookie: SID=x\n\n") == "cookie: SID=x"


def test_validate_auth_json_rejects_authorization_without_sapishash() -> None:
    with pytest.raises(ValueError, match="SAPISIDHASH"):
        validate_auth_json(_auth_json(authorization="Bearer xyz"))


def test_extract_cookie() -> None:
    auth = _auth_json(cookie="SID=aaa; __Secure-3PAPISID=bbb")
    assert extract_cookie(auth) == "SID=aaa; __Secure-3PAPISID=bbb"
    assert extract_cookie("{}") is None
    assert extract_cookie("not json") is None
    assert extract_cookie("[1]") is None


def test_player_clients() -> None:
    from app.services.youtube import player_clients

    # С куками android бесполезен (yt-dlp его скипает) — tv + web.
    assert player_clients(True) == ["tv", "web"]
    # Без кук android первым — обход bot-check.
    assert player_clients(False) == ["android", "web"]


def test_cookie_header_to_netscape_format() -> None:
    out = cookie_header_to_netscape("SID=aaa; __Secure-3PAPISID=bbb; broken; =x")
    lines = out.strip().split("\n")
    assert lines[0] == "# Netscape HTTP Cookie File"
    assert len(lines) == 3  # мусорные куски отброшены
    assert lines[1].split("\t")[:3] == [".youtube.com", "TRUE", "/"]
    assert lines[1].split("\t")[3] == "FALSE"  # SID — не Secure
    assert lines[2].split("\t")[3] == "TRUE"  # __Secure- — Secure
    assert lines[2].endswith("__Secure-3PAPISID\tbbb")
    expiry = int(lines[1].split("\t")[4])
    assert expiry > 1700000000  # осмысленный timestamp в будущем
