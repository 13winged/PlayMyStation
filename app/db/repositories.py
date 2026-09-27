"""CRUD-репозитории для users / integrations. Токены шифруются на запись."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_token, encrypt_token
from app.db.models import AuditLog, Integration, User


# ---------- Users ----------
async def get_or_create_user(session: AsyncSession, telegram_id: int) -> User:
    res = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = res.scalar_one_or_none()
    if user is None:
        user = User(telegram_id=telegram_id, active_provider="all")
        session.add(user)
        await session.flush()
    return user


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    res = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return res.scalar_one_or_none()


async def set_active_provider(session: AsyncSession, user: User, provider: str) -> User:
    if provider not in ("spotify", "yandex", "youtube", "lastfm", "all"):
        raise ValueError(f"Unknown provider: {provider}")
    user.active_provider = provider
    await session.flush()
    return user


async def set_language(session: AsyncSession, user: User, language: str) -> User:
    if language not in ("ru", "en"):
        raise ValueError(f"Unknown language: {language}")
    user.language = language
    await session.flush()
    return user


# ---------- Integrations ----------
async def upsert_integration(
    session: AsyncSession,
    user_id: int,
    provider: str,
    access_token: str | None,
    refresh_token: str | None = None,
    expires_at: dt.datetime | None = None,
    service_user_id: str | None = None,
) -> Integration:
    res = await session.execute(
        select(Integration).where(Integration.user_id == user_id, Integration.provider == provider)
    )
    row = res.scalar_one_or_none()
    if row is None:
        row = Integration(
            user_id=user_id,
            provider=provider,
            access_token=encrypt_token(access_token),
            refresh_token=encrypt_token(refresh_token),
            expires_at=expires_at,
            service_user_id=service_user_id,
        )
        session.add(row)
    else:
        if access_token is not None:
            row.access_token = encrypt_token(access_token)
        if refresh_token is not None:
            row.refresh_token = encrypt_token(refresh_token)
        row.expires_at = expires_at
        row.service_user_id = service_user_id
    await session.flush()
    return row


async def list_integrations(session: AsyncSession, user_id: int) -> list[Integration]:
    res = await session.execute(select(Integration).where(Integration.user_id == user_id))
    return list(res.scalars().all())


async def delete_integration(session: AsyncSession, user_id: int, provider: str) -> bool:
    res = await session.execute(
        select(Integration).where(Integration.user_id == user_id, Integration.provider == provider)
    )
    row = res.scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


def decrypted_access(integration: Integration) -> str | None:
    return decrypt_token(integration.access_token)


def decrypted_refresh(integration: Integration) -> str | None:
    return decrypt_token(integration.refresh_token)


async def log_audit(
    session: AsyncSession,
    user_id: int | None,
    telegram_id: int,
    action: str,
    provider: str,
    detail: str | None = None,
) -> AuditLog:
    """Записать событие подключения/отключения. Без секретов в detail!"""
    from app.core.metrics import audit_total

    row = AuditLog(
        user_id=user_id,
        telegram_id=telegram_id,
        action=action,
        provider=provider,
        detail=detail[:128] if detail else None,  # колонка varchar(128) — режем, не роняем
    )
    session.add(row)
    await session.flush()
    audit_total.labels(action, provider).inc()
    return row


async def recent_audit(
    session: AsyncSession, telegram_id: int, limit: int = 10
) -> list[AuditLog]:
    """Последние события юзера (для диагностики)."""
    res = await session.execute(
        select(AuditLog)
        .where(AuditLog.telegram_id == telegram_id)
        .order_by(AuditLog.id.desc())
        .limit(limit)
    )
    return list(res.scalars().all())
