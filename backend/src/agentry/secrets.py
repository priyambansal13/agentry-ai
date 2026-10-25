"""Encryption for stored credentials, and signed short-lived state tokens (OAuth CSRF protection)."""
import base64
import hashlib
import hmac
import json
import secrets as _secrets
import time

from cryptography.fernet import Fernet, InvalidToken

from agentry.config import settings


class SecretError(Exception):
    pass


def _fernet() -> Fernet:
    if not settings.encryption_key:
        raise SecretError("AGENTRY_ENCRYPTION_KEY is not set")
    return Fernet(settings.encryption_key.encode())


def encrypt_json(data: dict) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_json(token: str) -> dict:
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken as e:
        raise SecretError("cannot decrypt credentials (wrong AGENTRY_ENCRYPTION_KEY?)") from e


def _state_key() -> bytes:
    return hashlib.sha256(f"oauth-state:{settings.encryption_key}".encode()).digest()


def sign_state(payload: dict, ttl_seconds: int = 600) -> str:
    """Opaque, tamper-proof, expiring state for OAuth redirects: binds the callback to the org + user who started it."""
    body = json.dumps({**payload, "exp": int(time.time()) + ttl_seconds, "n": _secrets.token_hex(8)}, separators=(",", ":"))
    raw = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    sig = hmac.new(_state_key(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{raw}.{sig}"


def verify_state(state: str) -> dict:
    try:
        raw, sig = state.rsplit(".", 1)
    except ValueError as e:
        raise SecretError("malformed state") from e
    expected = hmac.new(_state_key(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        raise SecretError("state signature mismatch")
    payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    if payload["exp"] < time.time():
        raise SecretError("state expired, please try connecting again")
    return payload
