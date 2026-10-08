"""Explicit, one-time upload from the user's YouTube Music browser session."""

import asyncio
import json
import re

from fastapi import APIRouter, HTTPException, Request

from app.core.db import SessionFactory
from app.core.redis import invalidate_now_playing_cache
from app.core.security import _primary
from app.db import repositories as repo
from app.services.browser_pairing import consume_code
from app.services.youtube import check_auth, validate_auth_json

router = APIRouter(prefix="/connect", tags=["browser connection"])
MAX_BODY_BYTES = 32 * 1024
ALLOWED_HEADERS = {"authorization", "cookie", "x-goog-authuser", "x-goog-pageid"}


@router.post("/youtube")
async def connect_youtube(request: Request) -> dict:
    credential = request.headers.get("authorization", "")
    if not re.fullmatch(r"Bearer [A-Za-z0-9_-]{32}", credential):
        raise HTTPException(401, "Invalid pairing code")
    # Streaming limit also covers chunked uploads without Content-Length.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(413, "Request too large")
    try:
        payload = json.loads(body)
        headers = payload["headers"]
        if not isinstance(headers, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in headers.items()
        ):
            raise ValueError
        auth = {k.lower(): v for k, v in headers.items() if k.lower() in ALLOWED_HEADERS}
        auth_json = json.dumps(auth)
        validate_auth_json(auth_json)
    except (ValueError, TypeError, KeyError):
        # Pydantic validation errors can echo input: never return cookie values.
        raise HTTPException(400, "Incomplete YouTube Music headers") from None

    _primary()  # This route also runs in standalone web mode: no plaintext fallback.
    telegram_id = await consume_code(credential[7:])
    if telegram_id is None:
        raise HTTPException(401, "Pairing code expired or already used")
    # Consume before the external request so retries/concurrent uploads cannot
    # replace credentials twice. On failure the user requests a fresh code.
    try:
        async with asyncio.timeout(25):
            valid = await check_auth(auth_json)
    except TimeoutError:
        raise HTTPException(504, "YouTube Music verification timed out; get a new code") from None
    if not valid:
        raise HTTPException(400, "YouTube Music login failed; get a new code")
    async with SessionFactory() as session:
        user = await repo.get_or_create_user(session, telegram_id)
        await repo.upsert_integration(
            session, user_id=user.id, provider="youtube", access_token=auth_json
        )
        await repo.log_audit(session, user.id, telegram_id, "connect", "youtube", "extension")
        await session.commit()
    await invalidate_now_playing_cache(telegram_id)
    return {"ok": True, "provider": "youtube"}
