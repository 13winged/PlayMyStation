"""OAuth device-flow для YouTube Music (вход без DevTools).

Схема (Google OAuth для TV/limited-input устройств, через ytmusicapi):
1. `start_device_flow()` → user_code + verification_url (показываем юзеру).
2. Юзер открывает ссылку, вводит код, подтверждает доступ.
3. Фоновая задача поллит `exchange_once(device_code)` пока не получит токен.
4. Сохраняем oauth-JSON формата RefreshingToken.as_dict —
   YTMusic подхватывает его вместе с серверными oauth_credentials
   (авторефреш работает штатно, в БД ничего дописывать не надо).

Требует серверных YTM_OAUTH_CLIENT_ID/SECRET (Google Cloud Console:
YouTube Data API v3 включён, OAuth-клиент типа «TVs and Limited Input
devices»). Без них — только старый путь через заголовки браузера.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

log = logging.getLogger("playmystation.youtube_oauth")

# Ошибки поллинга, при которых просто ждём дальше.
_PENDING = "authorization_pending"
_SLOW_DOWN = "slow_down"


def is_oauth_json(auth_json: str | None) -> bool:
    """Это oauth-JSON (а не browser-headers JSON)?"""
    if not auth_json:
        return False
    try:
        data = json.loads(auth_json)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    # Зеркалим OAuthToken.is_oauth: полный набор полей токена.
    required = {"scope", "token_type", "access_token", "refresh_token", "expires_at", "expires_in"}
    return required <= {str(k) for k in data}


def server_oauth_credentials():  # type: ignore[no-untyped-def]
    """Серверные OAuthCredentials из настроек. None если не настроены."""
    from ytmusicapi import OAuthCredentials  # lazy import — тяжёлая зависимость

    from app.core.config import get_settings

    settings = get_settings()
    if not settings.ytm_oauth_client_id or not settings.ytm_oauth_client_secret:
        return None
    return OAuthCredentials(settings.ytm_oauth_client_id, settings.ytm_oauth_client_secret)


def oauth_configured() -> bool:
    from app.core.config import get_settings

    settings = get_settings()
    return bool(settings.ytm_oauth_client_id and settings.ytm_oauth_client_secret)


async def start_device_flow() -> dict:
    """Шаг 1: получить user_code + verification_url. Бросает при ошибке клиента."""
    creds = server_oauth_credentials()
    if creds is None:
        raise ValueError("YouTube OAuth is not configured on the server")
    code = await asyncio.to_thread(creds.get_code)
    return {
        "device_code": code["device_code"],
        "user_code": code["user_code"],
        "verification_url": code["verification_url"],
        "interval": int(code.get("interval", 5)),
        "expires_in": int(code.get("expires_in", 1800)),
    }


def build_oauth_token_dict(raw: dict) -> dict:
    """Шаг 3: сырой ответ token endpoint → oauth-JSON для БД.

    Повторяет RefreshingToken.prompt_for_token (без интерактива и файлов).
    """
    refresh_expires = raw.get("refresh_token_expires_in", raw.get("expires_in", 0))
    token = {
        "scope": raw.get("scope", ""),
        "token_type": raw.get("token_type", "Bearer"),
        "access_token": raw["access_token"],
        "refresh_token": raw["refresh_token"],
        "expires_in": int(refresh_expires or 0),
        "expires_at": int(time.time()) + int(raw.get("expires_in", 0)),
    }
    return token


def exchange_once(creds, device_code: str) -> tuple[str, dict | None]:  # type: ignore[no-untyped-def]
    """Одна попытка обмена device_code → токен. Синхронная (в to_thread).

    Возвращает (статус, payload): pending | slow_down | ok + raw |
    denied | expired | error + {"error": ...}.
    """
    try:
        raw = creds.token_from_code(device_code)
    except Exception as e:  # noqa: BLE001 — 401 клиента, сеть, всё сюда
        return "error", {"error": str(e)[:200]}
    if not isinstance(raw, dict):
        return "error", {"error": "bad response"}
    if raw.get("access_token"):
        return "ok", raw
    error = str(raw.get("error") or "unknown")
    if error == _PENDING:
        return "pending", None
    if error == _SLOW_DOWN:
        return "slow_down", None
    if error in ("access_denied",):
        return "denied", raw
    if error in ("expired_token", "invalid_grant"):
        return "expired", raw
    return "error", raw


def pick_streaming_url(song: dict) -> tuple[str, str] | None:
    """Выбрать аудио-поток из get_song(). Предпочитаем m4a (itag 140).

    Возвращает (url, ext) или None. Чистая функция.
    """
    formats = (song.get("streamingData") or {}).get("adaptiveFormats") or []
    if not isinstance(formats, list):
        return None
    audio_only = [f for f in formats if isinstance(f, dict) and f.get("url")]

    def _ext(fmt: dict) -> str:
        mime = str(fmt.get("mimeType") or "")
        if "audio/mp4" in mime:
            return "m4a"
        if "audio/webm" in mime:
            return "webm"
        return "m4a"

    for fmt in audio_only:
        if fmt.get("itag") == 140:
            return str(fmt["url"]), "m4a"
    for fmt in audio_only:
        if "audio/mp4" in str(fmt.get("mimeType") or ""):
            return str(fmt["url"]), "m4a"
    for fmt in audio_only:
        if str(fmt.get("mimeType") or "").startswith("audio/"):
            return str(fmt["url"]), _ext(fmt)
    return None


def fetch_streaming_sync(auth_json: str, video_id: str) -> tuple[str, str] | None:
    """Прямая ссылка на аудиопоток через OAuth-сессию юзера. Синхронная."""
    from ytmusicapi import YTMusic  # lazy import — тяжёлая зависимость

    creds = server_oauth_credentials()
    if creds is None:
        return None
    yt = YTMusic(auth=json.loads(auth_json), oauth_credentials=creds)
    song = yt.get_song(video_id)
    if not isinstance(song, dict):
        return None
    return pick_streaming_url(song)
