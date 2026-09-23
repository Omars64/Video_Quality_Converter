"""Password verification and short-lived signed sessions for the private app."""
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .config import settings

router = APIRouter(prefix="/api/auth")
_attempts: dict[str, list[float]] = {}
_lock = threading.Lock()
SESSION_SECONDS = 8 * 60 * 60


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000)
    return f"pbkdf2_sha256$600000${salt}${digest.hex()}"


def verify_password(password: str) -> bool:
    try:
        algorithm, rounds, salt, expected = settings.app_password_hash.split("$")
        if algorithm != "pbkdf2_sha256" or not 100_000 <= int(rounds) <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def signing_key() -> bytes:
    return (settings.session_secret or settings.api_key).encode()


def issue_session() -> str:
    payload = {"exp": int(time.time()) + SESSION_SECONDS, "nonce": secrets.token_hex(16), "scope": "media-forge"}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = hmac.new(signing_key(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def valid_session(token: str) -> bool:
    if not settings.app_password_hash or len(settings.session_secret) < 32 or len(token) > 1024:
        return False
    try:
        body, signature = token.split(".")
        expected = hmac.new(signing_key(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return False
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        now = int(time.time())
        return data.get("scope") == "media-forge" and now < data["exp"] <= now + SESSION_SECONDS
    except (ValueError, TypeError, KeyError):
        return False


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


@router.post("/login")
def login(payload: LoginRequest, request: Request):
    if not settings.app_password_hash or len(settings.session_secret) < 32:
        raise HTTPException(503, "Sign-in is not configured on the server. Please contact the app owner.")
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _lock:
        # Keep only recent attempts, including when requests come from new addresses.
        for key in list(_attempts):
            _attempts[key] = [stamp for stamp in _attempts[key] if stamp > now - 900]
            if not _attempts[key]:
                del _attempts[key]
        failures = _attempts.setdefault(client, [])
        if len(failures) >= 5 or len(_attempts) > 10_000:
            raise HTTPException(429, "Too many attempts. Please try again in 15 minutes.", headers={"Retry-After": "900"})
        failures.append(now)
    if not verify_password(payload.password):
        raise HTTPException(401, "Incorrect password.")
    with _lock:
        _attempts.pop(client, None)
    return {"token": issue_session(), "expiresIn": SESSION_SECONDS}


@router.get("/session")
def session():
    # The API middleware authenticates this route.
    return {"authenticated": True}
