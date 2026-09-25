"""Шифрование OAuth-токенов перед записью в БД (Fernet)."""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def _get_fernet() -> Fernet | None:
    key = get_settings().fernet_key
    try:
        return Fernet(key.encode())
    except Exception:
        return None


def encrypt_token(raw: str | None) -> str | None:
    if raw is None:
        return None
    f = _get_fernet()
    if f is None:
        return raw  # DEV-фолбэк: ключ не задан — храним как есть (не для прода!)
    return f.encrypt(raw.encode()).decode()


def decrypt_token(enc: str | None) -> str | None:
    if enc is None:
        return None
    f = _get_fernet()
    if f is None:
        return enc
    try:
        return f.decrypt(enc.encode()).decode()
    except InvalidToken:
        return enc  # токен был записан до включения шифрования
