"""Symmetric encryption for third-party tokens stored in the database
(Fernet, key derived from JWT_SECRET so no extra secret is required)."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def _fernet() -> Fernet:
    digest = hashlib.sha256(("tokens:" + get_settings().JWT_SECRET).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Stored token cannot be decrypted (JWT_SECRET changed?)") from exc
