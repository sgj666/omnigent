"""Authenticated encryption for provider credentials and delegated grants."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken


class FeishuCredentialError(ValueError):
    """Ciphertext failed authenticated decryption."""


class FeishuCredentialCipher:
    """Derive one Fernet key from operator-owned key material."""

    def __init__(self, key_material: bytes | str) -> None:
        raw = key_material.encode() if isinstance(key_material, str) else key_material
        self._fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw).digest()))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode("ascii")

    def decrypt(self, ciphertext: str | bytes) -> str:
        raw = ciphertext.encode("ascii") if isinstance(ciphertext, str) else ciphertext
        try:
            return self._fernet.decrypt(raw).decode()
        except (InvalidToken, UnicodeError, ValueError) as exc:
            raise FeishuCredentialError("invalid Feishu credential ciphertext") from exc


@dataclass(frozen=True)
class FeishuInstallationCredential:
    installation_id: str
    app_id: str
    app_secret_ciphertext: str
    installer_open_id: str


def encrypt_app_secret(secret: str, key_material: bytes | str) -> str:
    return FeishuCredentialCipher(key_material).encrypt(secret)


def decrypt_app_secret(ciphertext: str, key_material: bytes | str) -> str:
    return FeishuCredentialCipher(key_material).decrypt(ciphertext)


__all__ = [
    "FeishuCredentialCipher",
    "FeishuCredentialError",
    "FeishuInstallationCredential",
    "decrypt_app_secret",
    "encrypt_app_secret",
]
