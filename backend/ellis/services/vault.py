"""Application-layer encryption for sensitive values (AES-GCM with VAULT_KEY).

Decrypted only in the form filler and the clinic reveal endpoint. Models see masked tokens.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import settings


def _key() -> bytes:
    k = settings.vault_key
    if k:
        raw = base64.b64decode(k)
        if len(raw) in (16, 24, 32):
            return raw
    # Dev fallback: derived from the session secret. Set VAULT_KEY for any real use.
    return hashlib.sha256(("vault:" + settings.session_secret).encode()).digest()


def encrypt(plaintext: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt(blob: str) -> str:
    raw = base64.b64decode(blob)
    return AESGCM(_key()).decrypt(raw[:12], raw[12:], None).decode()
