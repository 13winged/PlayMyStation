"""Шифрование OAuth-токенов перед записью в БД (Fernet + ротация ключей).

Ротация (процедура — см. README «Ротация Fernet-ключей»):
1. FERNET_KEY=<новый>, FERNET_KEYS_OLD=<старый[,ещё-старее]> → деплой.
   Шифруем новым, расшифровываем любым из стека.
2. Одноразово: `docker compose exec app python -m app.core.security`
   (перешифровывает всё новым ключом, отчёт в stdout).
3. Убрать FERNET_KEYS_OLD → деплой.
"""

from __future__ import annotations

import asyncio
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

log = logging.getLogger("playmystation.security")


def _parse_keys(raw: str) -> list[Fernet]:
    out = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(Fernet(part.encode()))
        except Exception:  # noqa: BLE001 — битый ключ пропускаем
            log.warning("Ignoring invalid Fernet key")
    return out


def _primary() -> Fernet:
    """Primary-ключ для шифрования. Падает с понятной ошибкой, а не пишет plaintext."""
    settings = get_settings()
    keys = _parse_keys(settings.fernet_key)
    if not keys or settings.fernet_key.strip() == "CHANGE_ME":
        raise RuntimeError(
            "FERNET_KEY must be a valid 44-byte URL-safe base64 key "
            "(generate: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\")"
        )
    return keys[0]


def _get_fernets() -> list[Fernet]:
    """Стек ключей: [0] — primary для шифрования, остальные — только чтение."""
    settings = get_settings()
    try:
        primary = [_primary()]
    except RuntimeError:
        primary = []
    return primary + _parse_keys(settings.fernet_keys_old)


def encrypt_token(raw: str | None) -> str | None:
    if raw is None:
        return None
    fernets = _get_fernets()
    if not fernets:
        return raw  # DEV-фолбэк: ключей нет — храним как есть (не для прода!)
    return fernets[0].encrypt(raw.encode()).decode()


def decrypt_token(enc: str | None) -> str | None:
    if enc is None:
        return None
    fernets = _get_fernets()
    if not fernets:
        return enc
    for f in fernets:
        try:
            return f.decrypt(enc.encode()).decode()
        except InvalidToken:
            continue
    return enc  # токен записан до включения шифрования (plaintext legacy)


def needs_rotation(enc: str | None) -> bool:
    """True если значение НЕ расшифровывается primary-ключом (пора перешифровать)."""
    if enc is None:
        return False
    fernets = _get_fernets()
    if not fernets:
        return False
    try:
        fernets[0].decrypt(enc.encode())
        return False
    except InvalidToken:
        return True


async def reencrypt_all() -> tuple[int, int]:
    """Перешифровать все токены primary-ключом. Возвращает (всего, ротировано)."""
    from sqlalchemy import select

    from app.core.db import SessionFactory
    from app.db.models import Integration

    fernets = _get_fernets()
    if not fernets:
        raise ValueError("No valid FERNET_KEY — refusing to re-encrypt")
    primary = _primary()  # упадёт здесь же, если primary невалиден
    total = rotated = 0
    async with SessionFactory() as session:
        rows = list((await session.execute(select(Integration))).scalars().all())
        for row in rows:
            total += 1
            changed = False
            for attr in ("access_token", "refresh_token"):
                enc = getattr(row, attr)
                if enc is None or not needs_rotation(enc):
                    continue
                raw = decrypt_token(enc)
                if raw is None:
                    continue
                setattr(row, attr, primary.encrypt(raw.encode()).decode())
                changed = True
            if changed:
                rotated += 1
        await session.commit()
    return total, rotated


def main() -> None:
    total, rotated = asyncio.run(reencrypt_all())
    print(f"reencrypt: {rotated}/{total} integrations rotated to primary key")


if __name__ == "__main__":
    main()
