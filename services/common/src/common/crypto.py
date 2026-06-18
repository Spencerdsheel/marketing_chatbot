"""Crypto primitives: AES-256-GCM secret encryption + PBKDF2 password hashing.

We never invent crypto (KB ADR-009 / 07_SECURITY_PATTERNS). This module wraps the
``cryptography`` library and the stdlib ``hashlib``/``hmac`` with the platform's fixed
parameters:

- ``SecretBox`` — AES-256-GCM, a fresh random 96-bit nonce per encryption, authenticated
  (the GCM tag is verified on decrypt; tampering raises ``DecryptionError``). For provider
  API keys, OAuth tokens, and other secrets at rest.
- ``hash_password`` / ``verify_password`` — PBKDF2-SHA256, 120,000 iterations, a unique
  per-password salt, constant-time comparison.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from common.errors import AppException

_KEY_BYTES = 32          # AES-256
_NONCE_BYTES = 12        # 96-bit GCM nonce (recommended)
_PBKDF2_ALGO = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 120_000
_PBKDF2_SALT_BYTES = 16
_PBKDF2_DKLEN = 32


class DecryptionError(AppException):
    """Raised when a token cannot be authenticated/decrypted (tamper or wrong key)."""

    code = "DECRYPTION_FAILED"
    http_status = 500
    default_message = "Could not decrypt the protected value."


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _normalize_key(key: bytes | str) -> bytes:
    """Accept raw 32 bytes, 64-char hex, or base64url; return exactly 32 bytes."""
    if isinstance(key, (bytes, bytearray)):
        raw = bytes(key)
    else:
        text = key.strip()
        raw = b""
        if len(text) == _KEY_BYTES * 2:
            try:
                raw = bytes.fromhex(text)
            except ValueError:
                raw = b""
        if not raw:
            try:
                raw = _b64url_decode(text)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("SECRET_ENCRYPTION_KEY is not valid hex or base64url") from exc
    if len(raw) != _KEY_BYTES:
        raise ValueError(
            f"SECRET_ENCRYPTION_KEY must be {_KEY_BYTES} bytes (got {len(raw)})."
        )
    return raw


class SecretBox:
    """Authenticated symmetric encryption for secrets at rest (AES-256-GCM)."""

    def __init__(self, key: bytes | str) -> None:
        self._aead = AESGCM(_normalize_key(key))

    def encrypt(self, plaintext: str | bytes, *, aad: bytes | None = None) -> str:
        data = plaintext.encode("utf-8") if isinstance(plaintext, str) else plaintext
        nonce = secrets.token_bytes(_NONCE_BYTES)
        ciphertext = self._aead.encrypt(nonce, data, aad)
        return _b64url_encode(nonce + ciphertext)

    def decrypt(self, token: str, *, aad: bytes | None = None) -> bytes:
        try:
            blob = _b64url_decode(token)
            nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
            if len(nonce) != _NONCE_BYTES:
                raise ValueError("token too short")
            return self._aead.decrypt(nonce, ciphertext, aad)
        except (InvalidTag, ValueError, binascii.Error) as exc:
            raise DecryptionError() from exc

    def decrypt_str(self, token: str, *, aad: bytes | None = None) -> str:
        return self.decrypt(token, aad=aad).decode("utf-8")


def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-SHA256. Returns ``algo$iters$salt$hash`` (b64url)."""
    salt = secrets.token_bytes(_PBKDF2_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS, dklen=_PBKDF2_DKLEN
    )
    return f"{_PBKDF2_ALGO}${_PBKDF2_ITERATIONS}${_b64url_encode(salt)}${_b64url_encode(derived)}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time verify. Returns ``False`` on any malformed/unknown encoding."""
    try:
        algo, iters_s, salt_s, hash_s = encoded.split("$")
        if algo != _PBKDF2_ALGO:
            return False
        iterations = int(iters_s)
        salt = _b64url_decode(salt_s)
        expected = _b64url_decode(hash_s)
    except (ValueError, binascii.Error):
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations, dklen=len(expected)
    )
    return hmac.compare_digest(candidate, expected)
