"""Fernet encryption for user tokens and keys at rest. The key comes only from ENCRYPTION_KEY."""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from ..config import Settings

log = logging.getLogger("purrpost.crypto")


class CryptoError(Exception):
    pass


def _fernet(settings: Settings) -> Fernet:
    key = settings.encryption_key
    if not key:
        if not (settings.dev_auth or settings.dev_fake_providers):
            raise CryptoError("ENCRYPTION_KEY is not set")
        # Local development only: a fixed throwaway key so the app runs without setup
        key = base64.urlsafe_b64encode(hashlib.sha256(b"purrpost-dev-only-key").digest()).decode()
    try:
        return Fernet(key)
    except (ValueError, TypeError) as e:
        raise CryptoError("ENCRYPTION_KEY is not a valid Fernet key") from e


def encrypt(settings: Settings, plaintext: str) -> str:
    return _fernet(settings).encrypt(plaintext.encode()).decode()


def decrypt(settings: Settings, token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet(settings).decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise CryptoError("cannot decrypt: wrong ENCRYPTION_KEY?") from e


def mask(secret: str | None) -> str | None:
    """`sk-ant-…a1b2` for display: never the whole key."""
    if not secret:
        return None
    return f"{secret[:4]}…{secret[-4:]}" if len(secret) > 12 else "…"
