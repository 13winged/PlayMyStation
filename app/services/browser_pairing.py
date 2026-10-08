"""Short-lived browser pairing credentials, separate from Spotify OAuth state."""

import hashlib
import secrets

from app.core.redis import get_redis

PAIR_TTL = 600


def _key(code: str) -> str:
    # Redis keys and diagnostics must not contain usable pairing credentials.
    return "browser_pair:" + hashlib.sha256(code.encode()).hexdigest()


async def issue_code(telegram_id: int) -> str:
    code = secrets.token_urlsafe(24)
    redis = await get_redis()
    await redis.setex(_key(code), PAIR_TTL, str(telegram_id))
    return code


async def consume_code(code: str) -> int | None:
    redis = await get_redis()
    value = await redis.getdel(_key(code))
    return int(value) if value is not None else None
