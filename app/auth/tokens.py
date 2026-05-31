"""Signed tokens for the two flows that have to survive a round-trip
through an email inbox: email verification and password reset.

These are not session tokens. Sessions live in the database (see
`app.auth.sessions`) so they can be revoked individually. Email links
cannot rely on a database row because the token has to survive the user
clicking "verify" from a phone they will never log in on - it just has to
prove, on click, that the bearer once held that email. itsdangerous gives
us tamper evidence and an expiry baked into the token itself.
"""

import hashlib
import uuid
from typing import Protocol

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.settings import settings

# Each salt namespaces a serializer so a token signed for one purpose can
# never be replayed against another, even though they share the secret key.
_VERIFY_SALT = "pave-verify"
_RESET_SALT = "pave-reset"

# One day for email links: long enough to be usable, short enough to expire.
EMAIL_TOKEN_MAX_AGE = 24 * 60 * 60


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt=salt)


# --- email verification token ----------------------------------------------


def create_verification_token(user_id: uuid.UUID) -> str:
    """Sign a one-day token proving the holder controls this user's inbox."""
    return _serializer(_VERIFY_SALT).dumps(str(user_id))


def verify_verification_token(
    token: str, max_age: int = EMAIL_TOKEN_MAX_AGE
) -> uuid.UUID | None:
    try:
        raw = _serializer(_VERIFY_SALT).loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    try:
        return uuid.UUID(raw)
    except (ValueError, TypeError):
        return None


# --- password reset token (single-use) -------------------------------------


class _ResetSubject(Protocol):
    id: uuid.UUID
    password_hash: str | None


def pw_fingerprint(password_hash: str | None) -> str:
    """A short, stable digest of the current password hash.

    Embedding it in the token is what makes a reset single-use: a successful
    reset replaces password_hash, so the fingerprint baked into the old token
    no longer matches and the token is dead.
    """
    material = (password_hash or "").encode()
    return hashlib.sha256(material).hexdigest()[:16]


def create_reset_token(user: _ResetSubject) -> str:
    payload = f"{user.id}:{pw_fingerprint(user.password_hash)}"
    return _serializer(_RESET_SALT).dumps(payload)


def verify_reset_token(
    token: str, max_age: int = EMAIL_TOKEN_MAX_AGE
) -> tuple[uuid.UUID, str] | None:
    """Return (user_id, password fingerprint) the token was minted for.

    The caller must load that user and confirm the fingerprint still matches
    their current password hash; a mismatch means the token was already spent.
    """
    try:
        raw = _serializer(_RESET_SALT).loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(raw, str) or ":" not in raw:
        return None
    raw_id, _, fingerprint = raw.partition(":")
    try:
        return uuid.UUID(raw_id), fingerprint
    except (ValueError, TypeError):
        return None
