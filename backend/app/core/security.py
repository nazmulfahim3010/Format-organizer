"""Password hashing and signed tokens using only the standard library."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional

# OWASP minimum for scrypt: N=2^17, r=8, p=1 (about 128 MB of memory per hash)
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 17, 8, 1
MAX_PASSWORD_CHARS = 1024          # longer input is refused before hashing (denial of service)


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32, maxmem=256 * n * r + 64 * 1024 * 1024)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def _parse(stored: str):
    parts = stored.split("$")
    if len(parts) == 3 and parts[0] == "scrypt":                  # legacy: scrypt$salt$dk at N=2^14
        return 2 ** 14, 8, 1, parts[1], parts[2]
    if len(parts) == 6 and parts[0] == "scrypt":
        return int(parts[1]), int(parts[2]), int(parts[3]), parts[4], parts[5]
    raise ValueError("unknown hash format")


def verify_password(password: str, stored: str) -> bool:
    if len(password) > MAX_PASSWORD_CHARS:
        return False
    try:
        n, r, p, salt_b64, dk_b64 = _parse(stored)
        if n > 2 ** 20 or r > 32 or p > 4:                        # a tampered row must not exhaust memory
            return False
        test = _scrypt(password, base64.b64decode(salt_b64), n, r, p)
        return hmac.compare_digest(base64.b64decode(dk_b64), test)
    except Exception:
        return False


def needs_rehash(stored: str) -> bool:
    """True for hashes made with weaker parameters than today's (rehash them at the next login)."""
    try:
        n, r, p, _, _ = _parse(stored)
    except Exception:
        return True
    return (n, r, p) < (SCRYPT_N, SCRYPT_R, SCRYPT_P)


# a stored hash to spend the same time on unknown accounts (no user enumeration by timing)
_DUMMY_HASH = None


def burn_time(password: str) -> None:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("smartdoc-dummy-password")
    verify_password(password, _DUMMY_HASH)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def create_token(user_id: int, secret: str, ttl_seconds: int = 60 * 60 * 24 * 7) -> str:
    payload = _b64(json.dumps({"uid": user_id, "exp": int(time.time()) + ttl_seconds}, separators=(",", ":")).encode())
    sig = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(token: str, secret: str) -> Optional[int]:
    """Return the user id for a valid, unexpired token; otherwise None."""
    try:
        payload, sig = token.split(".")
        good = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        data = json.loads(_unb64(payload))
        if not isinstance(data, dict) or not isinstance(data.get("exp"), int) or data["exp"] < time.time():
            return None
        return int(data["uid"])
    except Exception:
        return None
