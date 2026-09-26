"""Тесты YouTube OAuth device-flow (моки, без сети и Google)."""

import json

from app.services.youtube_oauth import (
    build_oauth_token_dict,
    exchange_once,
    is_oauth_json,
    pick_streaming_url,
)


def _oauth_json(**overrides: object) -> str:
    base: dict[str, object] = {
        "scope": "https://www.googleapis.com/auth/youtube",
        "token_type": "Bearer",
        "access_token": "ya29.a",
        "refresh_token": "1//b",
        "expires_in": 3600,
        "expires_at": 1700000000,
    }
    base.update(overrides)
    return json.dumps(base)


def _browser_json() -> str:
    return json.dumps(
        {
            "authorization": "SAPISIDHASH 1_x",
            "cookie": "SID=a; __Secure-3PAPISID=b",
            "x-goog-authuser": "0",
        }
    )


class TestIsOauthJson:
    def test_oauth_detected(self) -> None:
        assert is_oauth_json(_oauth_json()) is True

    def test_browser_not_oauth(self) -> None:
        assert is_oauth_json(_browser_json()) is False

    def test_garbage_not_oauth(self) -> None:
        assert is_oauth_json(None) is False
        assert is_oauth_json("") is False
        assert is_oauth_json("not json") is False
        assert is_oauth_json("[1]") is False
        assert is_oauth_json("{}") is False


class TestBuildOauthTokenDict:
    def test_fields_mirror_prompt_for_token(self) -> None:
        raw = {
            "access_token": "ya29.a",
            "refresh_token": "1//b",
            "scope": "scope",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        token = build_oauth_token_dict(raw)
        assert token["access_token"] == "ya29.a"
        assert token["refresh_token"] == "1//b"
        assert token["expires_in"] == 3600
        assert token["expires_at"] > 1700000000
        assert is_oauth_json(json.dumps(token)) is True

    def test_prefers_refresh_token_expiry(self) -> None:
        raw = {
            "access_token": "a",
            "refresh_token": "b",
            "expires_in": 3600,
            "refresh_token_expires_in": 7200,
        }
        assert build_oauth_token_dict(raw)["expires_in"] == 7200


class FakeCreds:
    """Отдаёт заготовленные ответы token_from_code по очереди."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls = 0

    def token_from_code(self, device_code: str):
        assert device_code == "device-1"
        self.calls += 1
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


class TestExchangeOnce:
    def test_pending(self) -> None:
        creds = FakeCreds([{"error": "authorization_pending"}])
        assert exchange_once(creds, "device-1") == ("pending", None)

    def test_slow_down(self) -> None:
        creds = FakeCreds([{"error": "slow_down", "error_description": "x"}])
        assert exchange_once(creds, "device-1") == ("slow_down", None)

    def test_ok(self) -> None:
        raw = {"access_token": "a", "refresh_token": "b"}
        creds = FakeCreds([raw])
        assert exchange_once(creds, "device-1") == ("ok", raw)

    def test_denied(self) -> None:
        raw = {"error": "access_denied"}
        creds = FakeCreds([raw])
        assert exchange_once(creds, "device-1") == ("denied", raw)

    def test_expired(self) -> None:
        raw = {"error": "expired_token"}
        creds = FakeCreds([raw])
        assert exchange_once(creds, "device-1") == ("expired", raw)

    def test_exception_maps_to_error(self) -> None:
        creds = FakeCreds([RuntimeError("boom")])
        status, payload = exchange_once(creds, "device-1")
        assert status == "error"
        assert payload is not None and "boom" in str(payload.get("error"))


class TestPickStreamingUrl:
    def _song(self, formats: list) -> dict:
        return {"streamingData": {"adaptiveFormats": formats}}

    def test_prefers_itag_140(self) -> None:
        song = self._song(
            [
                {"itag": 251, "mimeType": 'audio/webm; codecs="opus"', "url": "https://w"},
                {"itag": 140, "mimeType": 'audio/mp4; codecs="mp4a.40.2"', "url": "https://m"},
            ]
        )
        assert pick_streaming_url(song) == ("https://m", "m4a")

    def test_falls_back_to_any_audio(self) -> None:
        song = self._song(
            [{"itag": 251, "mimeType": 'audio/webm; codecs="opus"', "url": "https://w"}]
        )
        assert pick_streaming_url(song) == ("https://w", "webm")

    def test_no_audio_returns_none(self) -> None:
        song = self._song([{"itag": 18, "mimeType": "video/mp4", "url": "https://v"}])
        assert pick_streaming_url(song) is None
        assert pick_streaming_url({}) is None
