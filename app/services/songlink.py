"""song.link-матчинг: кнопки «открыть этот же трек на …» в карточке.

API без ключа: GET https://api.song.link/v1-alpha.1/links?url=...&userCountry=US
Возвращает linksByPlatform (spotify/yandex/youtube/appleMusic/…).
Мэппинги стабильны — кешируем в Redis на 7 дней.
"""

from __future__ import annotations

import hashlib
import logging

import httpx

from app.core.retry import SONGLINK_CIRCUIT

log = logging.getLogger("playmystation.songlink")

API_URL = "https://api.song.link/v1-alpha.1/links"
REQUEST_TIMEOUT = 10.0

# Платформы, кнопки которых показываем (порядок = порядок кнопок).
WANTED_PLATFORMS: tuple[str, ...] = ("spotify", "yandex", "youtube")

# Домены, которые song.link умеет резолвить на входе.
SOURCE_DOMAINS: tuple[str, ...] = (
    "open.spotify.com",
    "music.yandex.ru",
    "music.youtube.com",
    "youtube.com",
    "youtu.be",
)


def source_supported(source_url: str) -> bool:
    """Умеет ли song.link резолвить такой URL."""
    lowered = source_url.lower()
    return any(d in lowered for d in SOURCE_DOMAINS)


def parse_links(data: dict, exclude: tuple[str, ...] = ()) -> dict[str, str]:
    """Вытащить {platform: url} из ответа API. Чистая функция."""
    by_platform = data.get("linksByPlatform") or {}
    if not isinstance(by_platform, dict):
        return {}
    links: dict[str, str] = {}
    for platform in WANTED_PLATFORMS:
        if platform in exclude:
            continue
        entry = by_platform.get(platform)
        if isinstance(entry, dict) and entry.get("url"):
            links[platform] = str(entry["url"])
    return links


async def match_platform_links(
    source_url: str, exclude: tuple[str, ...] = ()
) -> dict[str, str]:
    """Найти тот же трек на других платформах. {} если не нашлось."""
    if not source_supported(source_url):
        return {}
    from app.core.redis import get_cached_songlink, set_cached_songlink

    cached = await get_cached_songlink(source_url)
    if cached is not None:
        return {p: u for p, u in cached.items() if p not in exclude} if cached else {}
    if SONGLINK_CIRCUIT.is_open:
        return {}
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(
                API_URL, params={"url": source_url, "userCountry": "US"}
            )
    except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError):
        await SONGLINK_CIRCUIT.record_failure()
        return {}
    if resp.status_code != 200:
        if resp.status_code >= 500:
            await SONGLINK_CIRCUIT.record_failure()
        return {}
    try:
        data = resp.json()
    except ValueError:
        return {}
    await SONGLINK_CIRCUIT.record_success()
    links = parse_links(data if isinstance(data, dict) else {})
    await set_cached_songlink(source_url, links)
    return {p: u for p, u in links.items() if p not in exclude}


def songlink_cache_key(source_url: str) -> str:
    digest = hashlib.sha256(source_url.encode()).hexdigest()[:32]
    return f"songlink:{digest}"
