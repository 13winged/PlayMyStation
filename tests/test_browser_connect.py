"""Browser pairing tests: credentials never appear in validation responses."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.handlers.youtube_auth import cmd_browser_connect
from app.db import repositories as repo
from app.db.models import Base
from app.services.browser_pairing import consume_code, issue_code
from app.web.app import create_web_app

CODE = "a" * 32
HEADERS = {
    "cookie": "__Secure-3PAPISID=secret-cookie",
    "authorization": "SAPISIDHASH 1_test",
    "x-goog-authuser": "0",
}


def post(client, payload=None, code=CODE):
    return client.post("/connect/youtube", json=payload or {"headers": HEADERS},
                       headers={"Authorization": "Bearer " + code})


def test_invalid_code_rejected_before_body_processing():
    with TestClient(create_web_app()) as client:
        assert post(client, code="42").status_code == 401


@pytest.mark.parametrize("payload", [[], {"headers": []}, {"headers": {"cookie": "secret"}},
                                     {"headers": {"cookie": ["secret"]}}])
def test_malformed_body_does_not_echo_secrets(payload):
    with TestClient(create_web_app()) as client:
        response = client.post("/connect/youtube", json=payload,
                               headers={"Authorization": "Bearer " + CODE})
    assert response.status_code == 400
    assert "secret" not in response.text


def test_body_limit():
    with TestClient(create_web_app()) as client:
        response = client.post("/connect/youtube", content=b"x" * 32769,
                               headers={"Authorization": "Bearer " + CODE})
    assert response.status_code == 413


def test_expired_code_never_calls_google():
    with (
        patch("app.web.browser_connect.consume_code", new_callable=AsyncMock, return_value=None),
        patch("app.web.browser_connect.check_auth", new_callable=AsyncMock) as check,
        TestClient(create_web_app()) as client,
    ):
        assert post(client).status_code == 401
        check.assert_not_awaited()


@pytest.mark.parametrize("result,error,status", [(False, None, 400), (None, TimeoutError, 504)])
def test_failed_google_verification_never_saves(result, error, status):
    with (
        patch("app.web.browser_connect.consume_code", new_callable=AsyncMock, return_value=42),
        patch("app.web.browser_connect.check_auth", new_callable=AsyncMock,
              return_value=result, side_effect=error),
        patch("app.web.browser_connect.SessionFactory") as factory,
        TestClient(create_web_app()) as client,
    ):
        response = post(client)
        assert response.status_code == status
        factory.assert_not_called()
        assert "secret-cookie" not in response.text


async def test_success_is_encrypted_and_bound_to_code_owner():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        import httpx

        with (
            patch("app.web.browser_connect.consume_code", new_callable=AsyncMock, return_value=42),
            patch("app.web.browser_connect.check_auth", new_callable=AsyncMock, return_value=True),
            patch("app.web.browser_connect.SessionFactory", factory),
            patch("app.web.browser_connect.invalidate_now_playing_cache",
                  new_callable=AsyncMock) as invalidate,
        ):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_web_app()),
                                         base_url="http://test") as client:
                response = await client.post("/connect/youtube", json={
                    "telegram_id": 999, "headers": {**HEADERS, "unwanted": "discard"}
                }, headers={"Authorization": "Bearer " + CODE})
            assert response.status_code == 200
            invalidate.assert_awaited_once_with(42)
        async with factory() as session:
            user = await repo.get_user_by_telegram_id(session, 42)
            assert await repo.get_user_by_telegram_id(session, 999) is None
            integration = (await repo.list_integrations(session, user.id))[0]
            assert "secret-cookie" not in integration.access_token
            assert json.loads(repo.decrypted_access(integration)) == HEADERS
    finally:
        await engine.dispose()


async def test_code_has_ttl_and_is_consumed_atomically():
    redis = AsyncMock()
    redis.getdel.side_effect = ["42", None]
    with patch("app.services.browser_pairing.get_redis", new_callable=AsyncMock,
               return_value=redis):
        code = await issue_code(42)
        assert len(code) == 32
        key, ttl, owner = redis.setex.await_args.args
        assert code not in key and ttl == 600 and owner == "42"
        assert await consume_code(code) == 42
        assert await consume_code(code) is None
        redis.getdel.assert_awaited_with(key)


async def test_group_never_gets_pairing_code():
    message = SimpleNamespace(chat=SimpleNamespace(type="supergroup"), answer=AsyncMock())
    with patch("app.services.browser_pairing.issue_code", new_callable=AsyncMock) as issue:
        await cmd_browser_connect(message, SimpleNamespace(language="ru", telegram_id=42))
        issue.assert_not_awaited()
        assert "/youtube_connect" in message.answer.await_args.args[0]
