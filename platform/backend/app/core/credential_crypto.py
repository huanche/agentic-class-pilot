"""Per-user model credential encryption (stdlib-only, no external deps).

authenticated encryption via HMAC-SHA256 keystream (hash-nonce counter mode)
plus a deterministic HMAC tag. Key material comes from
`settings.CONFIG_ENCRYPTION_KEY`; missing key fails closed.
"""
import base64
import hashlib
import hmac
import os
import secrets

from app.core.config import settings

_NONCE_BYTES = 12


def _key() -> bytes:
    secret = settings.CONFIG_ENCRYPTION_KEY
    if not secret:
        raise RuntimeError("CONFIG_ENCRYPTION_KEY 未配置：无法加解密用户模型凭据")
    return hashlib.sha256(secret.encode()).digest()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    stream = b""
    counter = 0
    while len(stream) < length:
        stream += hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        counter += 1
    return stream[:length]


def encrypt(plaintext: str) -> str:
    nonce = secrets.token_bytes(_NONCE_BYTES)
    key = _key()
    cipher = bytes(a ^ b for a, b in zip(plaintext.encode("utf-8"), _keystream(key, nonce, len(plaintext.encode("utf-8")))))
    tag = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + cipher + tag).decode().rstrip("=")


def decrypt(token: str) -> str:
    key = _key()
    padded = token + "=" * (-len(token) % 4)
    raw = base64.urlsafe_b64decode(padded)
    nonce, cipher, tag = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:-32], raw[-32:]
    expected = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("凭据解密校验失败（密钥不匹配或数据被篡改）")
    plain = bytes(a ^ b for a, b in zip(cipher, _keystream(key, nonce, len(cipher))))
    return plain.decode("utf-8")
