"""Unit tests for crypto: AES-256-GCM SecretBox + PBKDF2 password hashing.

We do not roll our own crypto — these tests assert the *contract* (round-trip,
unique nonce, tamper detection, key handling, salted password hashing).
"""
import base64
import secrets

import pytest

from common.crypto import (
    DecryptionError,
    SecretBox,
    hash_password,
    verify_password,
)


def _key32_bytes() -> bytes:
    return secrets.token_bytes(32)


# --------------------------------------------------------------------- SecretBox

def test_secretbox_roundtrip_str() -> None:
    box = SecretBox(_key32_bytes())
    token = box.encrypt("sk-provider-secret")
    assert isinstance(token, str)
    assert box.decrypt(token) == b"sk-provider-secret"


def test_secretbox_roundtrip_bytes() -> None:
    box = SecretBox(_key32_bytes())
    assert box.decrypt(box.encrypt(b"\x00\x01\x02bytes")) == b"\x00\x01\x02bytes"


def test_secretbox_decrypt_str_helper() -> None:
    box = SecretBox(_key32_bytes())
    assert box.decrypt_str(box.encrypt("hello")) == "hello"


def test_ciphertext_differs_each_time_unique_nonce() -> None:
    box = SecretBox(_key32_bytes())
    a = box.encrypt("same plaintext")
    b = box.encrypt("same plaintext")
    assert a != b  # unique nonce per encryption
    assert box.decrypt(a) == box.decrypt(b)


def test_tampered_token_is_rejected() -> None:
    box = SecretBox(_key32_bytes())
    token = box.encrypt("secret")
    raw = bytearray(base64.urlsafe_b64decode(token + "=="))
    raw[-1] ^= 0x01  # flip a bit in the auth tag
    tampered = base64.urlsafe_b64encode(bytes(raw)).rstrip(b"=").decode()
    with pytest.raises(DecryptionError):
        box.decrypt(tampered)


def test_wrong_key_cannot_decrypt() -> None:
    token = SecretBox(_key32_bytes()).encrypt("secret")
    with pytest.raises(DecryptionError):
        SecretBox(_key32_bytes()).decrypt(token)


def test_garbage_token_is_rejected() -> None:
    with pytest.raises(DecryptionError):
        SecretBox(_key32_bytes()).decrypt("not-a-valid-token!!!")


def test_key_accepts_hex_and_base64url() -> None:
    raw = _key32_bytes()
    hex_key = raw.hex()
    b64_key = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    msg = "x"
    # a token from the bytes key decrypts with the same key expressed as hex/b64
    token = SecretBox(raw).encrypt(msg)
    assert SecretBox(hex_key).decrypt_str(token) == msg
    assert SecretBox(b64_key).decrypt_str(token) == msg


def test_key_wrong_length_rejected() -> None:
    with pytest.raises(ValueError):
        SecretBox(b"too-short")


# ----------------------------------------------------------------- passwords

def test_hash_then_verify_succeeds() -> None:
    enc = hash_password("Sup3r-secret!")
    assert verify_password("Sup3r-secret!", enc) is True


def test_verify_rejects_wrong_password() -> None:
    enc = hash_password("correct horse")
    assert verify_password("battery staple", enc) is False


def test_same_password_hashes_differently_salted() -> None:
    assert hash_password("pw") != hash_password("pw")


def test_encoded_format_is_pbkdf2_sha256_120k() -> None:
    enc = hash_password("pw")
    algo, iters, _salt, _hash = enc.split("$")
    assert algo == "pbkdf2_sha256"
    assert int(iters) == 120_000


def test_verify_on_malformed_hash_returns_false() -> None:
    assert verify_password("pw", "not-a-valid-encoded-hash") is False
    assert verify_password("pw", "") is False
