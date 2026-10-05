"""
Session tokens and at-rest encryption of OAuth refresh tokens.
"""

from __future__ import annotations

import hashlib
import secrets

from cryptography.fernet import Fernet, InvalidToken

from src.core.config import get_settings


def new_token() -> str:
    """Return an unguessable URL-safe token (256 bits)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash a session token for storage.

    A plain SHA-256 is enough: the input is 256 random bits, so there is
    nothing to brute-force and no need for a slow password hash.
    """
    return hashlib.sha256(token.encode()).hexdigest()


class TokenEncryptionError(RuntimeError):
    """Raised when the encryption key is missing or a ciphertext is unreadable."""


def _fernet() -> Fernet:
    key = get_settings().TOKEN_ENCRYPTION_KEY
    if not key:
        raise TokenEncryptionError("TOKEN_ENCRYPTION_KEY is not set.")
    try:
        return Fernet(key)
    except ValueError as exc:
        raise TokenEncryptionError(
            "TOKEN_ENCRYPTION_KEY is not a valid Fernet key."
        ) from exc


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise TokenEncryptionError(
            "Stored token cannot be decrypted; was TOKEN_ENCRYPTION_KEY changed?"
        ) from exc
