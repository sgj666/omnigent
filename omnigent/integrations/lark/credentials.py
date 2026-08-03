"""Authenticated encryption for Feishu app secrets."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken


class FeishuCredentialError(ValueError):
    """Raised when ciphertext cannot be decrypted with the server key."""


class FeishuCredentialCipher:
    """Encrypt Feishu app secrets using a server-owned key material.

    The input is normally the accounts cookie secret.  It is hashed and encoded
    into a Fernet key so ciphertext is authenticated as well as confidential.
    No caller should serialize the returned plaintext outside the immediate
    Feishu API request that needs it.
    """

    def __init__(self, key_material: bytes | str) -> None:
        if isinstance(key_material, str):
            key_material = key_material.encode("utf-8")
        key = base64.urlsafe_b64encode(hashlib.sha256(key_material).digest())
        self._fernet = Fernet(key)

    def encrypt(self, secret: str) -> str:
        """Return authenticated ciphertext for an app secret."""
        return self._fernet.encrypt(secret.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        """Recover an app secret, rejecting tampered ciphertext."""
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError) as exc:
            raise FeishuCredentialError("invalid Feishu credential ciphertext") from exc


@dataclass(frozen=True)
class FeishuInstallationCredential:
    """Persistence payload containing ciphertext only, never a raw secret."""

    installation_id: str
    app_id: str
    app_secret_ciphertext: str
    installer_open_id: str


def encrypt_app_secret(secret: str, key_material: bytes | str) -> str:
    """Convenience wrapper for one-off credential encryption."""
    return FeishuCredentialCipher(key_material).encrypt(secret)


def decrypt_app_secret(ciphertext: str, key_material: bytes | str) -> str:
    """Convenience wrapper for controlled runtime credential retrieval."""
    return FeishuCredentialCipher(key_material).decrypt(ciphertext)
