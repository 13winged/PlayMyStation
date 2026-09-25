"""SoundCloud: OAuth2 + история прослушиваний.

У SoundCloud нет realtime 'currently playing' в public API,
поэтому берём последний трек из /me/play-history (или /me/activities)
и помечаем is_playing=False c пометкой 'last played'.
Если в будущем появится realtime endpoint — заменить только этот класс.
"""

from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.services.base import BaseMusicService, TrackDTO


def build_authorize_url(state: str) -> str:
    s = get_settings()
    from urllib.parse import urlencode

    params = {
        "client_id": s.soundcloud_client_id,
        "redirect_uri": s.soundcloud_redirect_uri,
        "response_type": "code",
        "state": state,
    }
    return "https://secure.soundcloud.com/authorize?" + urlencode(params)


class SoundCloudService(BaseMusicService):
    provider = "soundcloud"

    def __init__(self, access_token: str) -> None:
        self._access_token = access_token

    async def get_currently_playing(self) -> TrackDTO | None:
        headers = {"Authorization": f"OAuth {self._access_token}"}
        async with httpx.AsyncClient(timeout=15) as client:
            # 1) пробуем play-history (новый API)
            resp = await client.get(
                "https://api.soundcloud.com/me/play-history",
                headers=headers,
                params={"limit": 1},
            )
            if resp.status_code == 401:
                return None
            items: list = []
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("collection", []) if isinstance(data, dict) else []
            # 2) фолбэк: последние лайки как 'recently played'
            if not items:
                fav = await client.get(
                    "https://api.soundcloud.com/me/favorites",
                    headers=headers,
                    params={"limit": 1},
                )
                if fav.status_code == 200 and isinstance(fav.json(), list) and fav.json():
                    t = fav.json()[0]
                    return self._to_dto(t, is_playing=False)
                return None
            raw = items[0].get("track", items[0])
            return self._to_dto(raw, is_playing=False)

    @staticmethod
    def _to_dto(t: dict, is_playing: bool) -> TrackDTO:
        artwork = t.get("artwork_url")
        if artwork:
            artwork = artwork.replace("large", "t500x500")
        user = t.get("user") or {}
        return TrackDTO(
            title=t.get("title", "Unknown title"),
            artist=user.get("username", "Unknown artist"),
            album=None,
            duration_ms=t.get("duration_milliseconds"),
            progress_ms=None,
            is_playing=is_playing,
            cover_url=artwork,
            track_url=t.get("permalink_url"),
            provider="soundcloud",
        )
