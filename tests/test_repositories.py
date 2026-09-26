"""Тесты репозиториев с in-memory SQLite."""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import decrypt_token, encrypt_token
from app.db import repositories as repo
from app.db.models import Base

# In-memory SQLite для тестов
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

# Генерация валидного FERNET_KEY для тестов
_test_fernet_key = Fernet.generate_key().decode()
os.environ["FERNET_KEY"] = _test_fernet_key


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def session(session_factory):
    async with session_factory() as s:
        yield s


class TestUserRepository:
    """Тесты репозитория пользователей."""

    @pytest.mark.asyncio
    async def test_get_or_create_user_creates_new(self, session: AsyncSession) -> None:
        user = await repo.get_or_create_user(session, 123456789)
        assert user.telegram_id == 123456789
        assert user.active_provider == "all"
        assert user.id is not None

    @pytest.mark.asyncio
    async def test_get_or_create_user_returns_existing(self, session: AsyncSession) -> None:
        user1 = await repo.get_or_create_user(session, 123456789)
        user2 = await repo.get_or_create_user(session, 123456789)
        assert user1.id == user2.id

    @pytest.mark.asyncio
    async def test_get_user_by_telegram_id(self, session: AsyncSession) -> None:
        await repo.get_or_create_user(session, 123456789)
        user = await repo.get_user_by_telegram_id(session, 123456789)
        assert user is not None
        assert user.telegram_id == 123456789

    @pytest.mark.asyncio
    async def test_get_user_by_telegram_id_not_found(self, session: AsyncSession) -> None:
        user = await repo.get_user_by_telegram_id(session, 999999999)
        assert user is None

    @pytest.mark.asyncio
    async def test_set_active_provider(self, session: AsyncSession) -> None:
        user = await repo.get_or_create_user(session, 123456789)
        updated = await repo.set_active_provider(session, user, "spotify")
        assert updated.active_provider == "spotify"

    @pytest.mark.asyncio
    async def test_set_active_provider_invalid_raises(self, session: AsyncSession) -> None:
        user = await repo.get_or_create_user(session, 123456789)
        with pytest.raises(ValueError):
            await repo.set_active_provider(session, user, "invalid")

    @pytest.mark.asyncio
    async def test_set_language(self, session: AsyncSession) -> None:
        user = await repo.get_or_create_user(session, 123456789)
        assert user.language == "ru"
        updated = await repo.set_language(session, user, "en")
        assert updated.language == "en"

    @pytest.mark.asyncio
    async def test_set_language_invalid_raises(self, session: AsyncSession) -> None:
        user = await repo.get_or_create_user(session, 123456789)
        with pytest.raises(ValueError):
            await repo.set_language(session, user, "de")


class TestIntegrationRepository:
    """Тесты репозитория интеграций."""

    @pytest.mark.asyncio
    async def test_upsert_integration_creates_new(self, session: AsyncSession) -> None:
        user = await repo.get_or_create_user(session, 123456789)
        integ = await repo.upsert_integration(
            session,
            user_id=user.id,
            provider="spotify",
            access_token="token123",
            refresh_token="refresh123",
        )
        assert integ.provider == "spotify"
        assert integ.access_token is not None
        assert integ.refresh_token is not None

    @pytest.mark.asyncio
    async def test_upsert_integration_updates_existing(self, session: AsyncSession) -> None:
        user = await repo.get_or_create_user(session, 123456789)
        await repo.upsert_integration(session, user.id, "spotify", "old_token")
        integ = await repo.upsert_integration(session, user.id, "spotify", "new_token")
        assert integ.access_token is not None
        decrypted = decrypt_token(integ.access_token)
        assert decrypted == "new_token"

    @pytest.mark.asyncio
    async def test_list_integrations(self, session: AsyncSession) -> None:
        user = await repo.get_or_create_user(session, 123456789)
        await repo.upsert_integration(session, user.id, "spotify", "token1")
        await repo.upsert_integration(session, user.id, "yandex", "token2")

        integrations = await repo.list_integrations(session, user.id)
        assert len(integrations) == 2
        providers = {i.provider for i in integrations}
        assert providers == {"spotify", "yandex"}

    @pytest.mark.asyncio
    async def test_delete_integration(self, session: AsyncSession) -> None:
        user = await repo.get_or_create_user(session, 123456789)
        await repo.upsert_integration(session, user.id, "spotify", "token1")
        await repo.upsert_integration(session, user.id, "yandex", "token2")

        deleted = await repo.delete_integration(session, user.id, "spotify")
        assert deleted is True

        integrations = await repo.list_integrations(session, user.id)
        assert len(integrations) == 1
        assert integrations[0].provider == "yandex"

    @pytest.mark.asyncio
    async def test_delete_integration_not_found(self, session: AsyncSession) -> None:
        user = await repo.get_or_create_user(session, 123456789)
        deleted = await repo.delete_integration(session, user.id, "spotify")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_unique_constraint_user_provider(self, session: AsyncSession) -> None:
        """UniqueConstraint(user_id, provider) предотвращает дубли."""
        user = await repo.get_or_create_user(session, 123456789)
        await repo.upsert_integration(session, user.id, "spotify", "token1")

        integ = await repo.upsert_integration(session, user.id, "spotify", "token2")
        integrations = await repo.list_integrations(session, user.id)
        assert len(integrations) == 1
        assert decrypt_token(integ.access_token) == "token2"


class TestTokenEncryption:
    """Тесты шифрования токенов."""

    def test_encrypt_decrypt_roundtrip(self) -> None:
        original = "super_secret_token_123"
        encrypted = encrypt_token(original)
        assert encrypted != original
        decrypted = decrypt_token(encrypted)
        assert decrypted == original

    def test_encrypt_decrypt_none(self) -> None:
        assert encrypt_token(None) is None
        assert decrypt_token(None) is None

    def test_decrypt_unencrypted_fallback(self) -> None:
        # Если токен записан без шифрования (DEV fallback)
        raw = "plain_token"
        assert decrypt_token(raw) == raw