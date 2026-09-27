"""Тесты ротации Fernet-ключей (моки настроек + sqlite, без прод-БД)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.security as sec
from app.db import repositories as repo
from app.db.models import Base, Integration, User

OLD_KEY = Fernet.generate_key().decode()
NEW_KEY = Fernet.generate_key().decode()


def _settings(primary: str, old: str = "") -> SimpleNamespace:
    return SimpleNamespace(fernet_key=primary, fernet_keys_old=old)


def _patch_settings(primary: str, old: str = ""):
    return patch.object(sec, "get_settings", return_value=_settings(primary, old))


class TestMultiKey:
    def test_encrypt_decrypt_primary(self) -> None:
        with _patch_settings(NEW_KEY):
            enc = sec.encrypt_token("secret")
            assert enc != "secret"
            assert sec.decrypt_token(enc) == "secret"

    def test_decrypt_falls_back_to_old_key(self) -> None:
        with _patch_settings(OLD_KEY):
            enc = sec.encrypt_token("secret")
        with _patch_settings(NEW_KEY, OLD_KEY):
            assert sec.decrypt_token(enc) == "secret"

    def test_unknown_ciphertext_returns_as_is(self) -> None:
        with _patch_settings(NEW_KEY):
            assert sec.decrypt_token("plain-legacy") == "plain-legacy"

    def test_needs_rotation(self) -> None:
        with _patch_settings(OLD_KEY):
            enc = sec.encrypt_token("secret")
        with _patch_settings(NEW_KEY, OLD_KEY):
            assert sec.needs_rotation(enc) is True
        with _patch_settings(NEW_KEY):
            fresh = sec.encrypt_token("secret")
            assert sec.needs_rotation(fresh) is False
            assert sec.needs_rotation(None) is False


@pytest_asyncio.fixture
async def mem_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


class TestReencrypt:
    @pytest.mark.asyncio
    async def test_reencrypt_all_moves_to_primary(self, mem_factory) -> None:
        async with mem_factory() as session:
            user = User(telegram_id=1, active_provider="all")
            session.add(user)
            await session.flush()
            with _patch_settings(OLD_KEY):
                session.add(
                    Integration(
                        user_id=user.id,
                        provider="spotify",
                        access_token=sec.encrypt_token("tok"),
                        refresh_token=sec.encrypt_token("ref"),
                    )
                )
                await session.commit()

            with (
                _patch_settings(NEW_KEY, OLD_KEY),
                patch("app.core.db.SessionFactory", mem_factory),
            ):
                total, rotated = await sec.reencrypt_all()

            assert (total, rotated) == (1, 1)
            with _patch_settings(NEW_KEY):  # только новый ключ — читается
                rows = await repo.list_integrations(session, user.id)
                assert repo.decrypted_access(rows[0]) == "tok"
                assert repo.decrypted_refresh(rows[0]) == "ref"

    @pytest.mark.asyncio
    async def test_reencrypt_without_valid_key_refuses(self, mem_factory) -> None:
        with (
            _patch_settings("not-a-key"),
            patch("app.core.db.SessionFactory", mem_factory),
            pytest.raises(ValueError),
        ):
            await sec.reencrypt_all()


class TestAuditLog:
    @pytest.mark.asyncio
    async def test_log_and_recent_audit(self, mem_factory) -> None:
        async with mem_factory() as session:
            user = await repo.get_or_create_user(session, 111)
            await repo.log_audit(session, user.id, 111, "connect", "spotify", "oauth")
            await repo.log_audit(session, user.id, 111, "disconnect", "spotify", "x")
            await session.commit()
            recent = await repo.recent_audit(session, 111)
            assert [r.action for r in recent] == ["disconnect", "connect"]
            assert recent[0].provider == "spotify"
            assert recent[0].telegram_id == 111
