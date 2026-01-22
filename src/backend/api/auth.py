"""Auth helpers for session cookies and password hashing."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Tuple
from uuid import uuid4

from flask import Response, request

from ..storage.auth import AuthSession, AuthStore, AuthUser

PASSWORD_HASH_ALGO = "pbkdf2_sha256"
DEFAULT_PASSWORD_ITERATIONS = 390_000
DEFAULT_SESSION_TTL_HOURS = 12
DEFAULT_REMEMBER_TTL_HOURS = 24 * 14
DEFAULT_MIN_PASSWORD_LENGTH = 10
DEFAULT_MAX_PASSWORD_LENGTH = 256
DEFAULT_MAX_SESSIONS_PER_USER = 5

SESSION_COOKIE_NAME = "lemon_session"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class AuthConfig:
    password_iterations: int
    min_password_length: int
    max_password_length: int
    session_ttl_hours: int
    remember_ttl_hours: int
    max_sessions_per_user: int
    cookie_secure: bool
    cookie_samesite: str


class LoginRateLimiter:
    def __init__(self, *, limit: int, window_seconds: int, block_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self.block_seconds = block_seconds
        self._attempts: dict[str, dict[str, float]] = {}

    def is_allowed(self, key: str) -> Tuple[bool, int]:
        now = time.time()
        entry = self._attempts.get(key)
        if entry:
            blocked_until = entry.get("blocked_until", 0)
            if blocked_until > now:
                return False, int(blocked_until - now)
            if now > entry.get("reset_at", 0):
                entry = None
        if not entry:
            self._attempts[key] = {
                "count": 0,
                "reset_at": now + self.window_seconds,
                "blocked_until": 0,
            }
        return True, 0

    def add_failure(self, key: str) -> None:
        now = time.time()
        entry = self._attempts.get(key)
        if not entry or now > entry.get("reset_at", 0):
            entry = {
                "count": 0,
                "reset_at": now + self.window_seconds,
                "blocked_until": 0,
            }
            self._attempts[key] = entry
        entry["count"] = entry.get("count", 0) + 1
        if entry["count"] >= self.limit:
            entry["blocked_until"] = now + self.block_seconds


login_rate_limiter = LoginRateLimiter(limit=8, window_seconds=10 * 60, block_seconds=10 * 60)


def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _get_cookie_samesite() -> str:
    value = os.getenv("LEMON_SESSION_SAMESITE", "Lax").strip()
    if value.lower() in {"lax", "strict", "none"}:
        return value.capitalize()
    return "Lax"


def _get_cookie_secure() -> bool:
    value = os.getenv("LEMON_SECURE_COOKIES")
    if value is not None:
        return value.lower() in {"1", "true", "yes"}
    env = os.getenv("LEMON_ENV", "").lower() or os.getenv("FLASK_ENV", "").lower()
    return env == "production"


def get_auth_config() -> AuthConfig:
    return AuthConfig(
        password_iterations=_get_int_env("LEMON_PASSWORD_HASH_ITERATIONS", DEFAULT_PASSWORD_ITERATIONS),
        min_password_length=_get_int_env("LEMON_MIN_PASSWORD_LENGTH", DEFAULT_MIN_PASSWORD_LENGTH),
        max_password_length=_get_int_env("LEMON_MAX_PASSWORD_LENGTH", DEFAULT_MAX_PASSWORD_LENGTH),
        session_ttl_hours=_get_int_env("LEMON_AUTH_SESSION_TTL_HOURS", DEFAULT_SESSION_TTL_HOURS),
        remember_ttl_hours=_get_int_env("LEMON_AUTH_REMEMBER_TTL_HOURS", DEFAULT_REMEMBER_TTL_HOURS),
        max_sessions_per_user=_get_int_env("LEMON_AUTH_MAX_SESSIONS", DEFAULT_MAX_SESSIONS_PER_USER),
        cookie_secure=_get_cookie_secure(),
        cookie_samesite=_get_cookie_samesite(),
    )


def is_registration_allowed() -> bool:
    value = os.getenv("LEMON_ALLOW_REGISTRATION", "").strip().lower()
    return value in {"1", "true", "yes"}


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_email(email: str) -> Optional[str]:
    if not email:
        return "Email is required."
    if len(email) > 320:
        return "Email is too long."
    if not EMAIL_RE.match(email):
        return "Email format is invalid."
    return None


def validate_password(password: str, config: AuthConfig) -> Iterable[str]:
    if not password:
        return ["Password is required."]
    errors = []
    if len(password) < config.min_password_length:
        errors.append(f"Password must be at least {config.min_password_length} characters.")
    if len(password) > config.max_password_length:
        errors.append("Password is too long.")
    if not any(char.isalpha() for char in password):
        errors.append("Password must include at least one letter.")
    if not any(char.isdigit() for char in password):
        errors.append("Password must include at least one number.")
    return errors


def _pbkdf2_hash(password: str, *, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def hash_password(password: str, *, config: AuthConfig) -> str:
    salt = secrets.token_bytes(16)
    hashed = _pbkdf2_hash(password, salt=salt, iterations=config.password_iterations)
    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii")
    hash_b64 = base64.urlsafe_b64encode(hashed).decode("ascii")
    return f"{PASSWORD_HASH_ALGO}${config.password_iterations}${salt_b64}${hash_b64}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algo, iterations_raw, salt_b64, hash_b64 = stored_hash.split("$", 3)
    except ValueError:
        return False
    if algo != PASSWORD_HASH_ALGO:
        return False
    try:
        iterations = int(iterations_raw)
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected = base64.urlsafe_b64decode(hash_b64.encode("ascii"))
    except (ValueError, base64.binascii.Error):
        return False
    computed = _pbkdf2_hash(password, salt=salt, iterations=iterations)
    return hmac.compare_digest(computed, expected)


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def is_session_expired(session: AuthSession) -> bool:
    expires_at = _parse_datetime(session.expires_at)
    if not expires_at:
        return True
    return expires_at <= _now()


def issue_session(
    auth_store: AuthStore,
    *,
    user_id: str,
    remember: bool,
    config: AuthConfig,
) -> Tuple[str, str]:
    token = generate_session_token()
    token_hash = hash_session_token(token)
    ttl_hours = config.remember_ttl_hours if remember else config.session_ttl_hours
    expires_at = (_now() + timedelta(hours=ttl_hours)).isoformat()
    session_id = f"sess_{uuid4().hex}"
    auth_store.delete_expired_sessions()
    auth_store.create_session(session_id, user_id, token_hash, expires_at=expires_at)
    auth_store.prune_sessions(user_id, max_sessions=config.max_sessions_per_user)
    return token, expires_at


def get_session_from_request(auth_store: AuthStore) -> Optional[Tuple[AuthSession, AuthUser]]:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    token_hash = hash_session_token(token)
    result = auth_store.get_session_by_token_hash(token_hash)
    if not result:
        return None
    session, user = result
    if is_session_expired(session):
        auth_store.delete_session_by_token_hash(token_hash)
        return None
    auth_store.touch_session(session.id)
    return session, user


def set_session_cookie(response: Response, token: str, expires_at: str, *, config: AuthConfig) -> None:
    expires_dt = _parse_datetime(expires_at)
    max_age = None
    if expires_dt:
        max_age = max(int((expires_dt - _now()).total_seconds()), 0)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=max_age,
        expires=expires_dt,
        httponly=True,
        secure=config.cookie_secure,
        samesite=config.cookie_samesite,
        path="/",
    )


def clear_session_cookie(response: Response, *, config: AuthConfig) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        samesite=config.cookie_samesite,
        secure=config.cookie_secure,
    )


def apply_login_rate_limit(identifier: str) -> Optional[Response]:
    allowed, retry_after = login_rate_limiter.is_allowed(identifier)
    if allowed:
        return None
    response = Response(
        response='{"error":"Too many attempts. Try again later."}',
        status=429,
        mimetype="application/json",
    )
    response.headers["Retry-After"] = str(retry_after)
    return response


def note_login_failure(identifier: str) -> None:
    login_rate_limiter.add_failure(identifier)
