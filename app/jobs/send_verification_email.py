"""Off-request verification-email job.

Signup must return quickly, but the email provider can be slow or flaky (a
transient 5xx from the HTTP endpoint, a DNS hiccup, a rate-limit window).
Awaiting `send_email` inside the signup handler couples request latency to
the provider's worst case, and a provider error there would either bubble a
500 (and the user thinks signup failed even though their row was committed)
or be swallowed silently.

Pulling the send off the request path fixes both: the route commits the user
and enqueues this job, Soniq runs it with its own retry/backoff, and signup
returns 303 in single-digit milliseconds.

The job receives an id, never a full ORM object, and the session is a
parameter. The verification token is minted *inside* the job from the user's
current id so a queued send that runs after an account is deleted does nothing
instead of leaking a token for a row that no longer exists.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import create_verification_token
from app.email import render_email, send_email
from app.models.user import User


async def send_verification_email(
    user_id: uuid.UUID, verify_base_url: str, db: AsyncSession
) -> None:
    user = await db.get(User, user_id)
    if user is None:
        return  # idempotent: account deleted between enqueue and run
    if user.email_verified_at is not None:
        return  # already verified - nothing to do

    token = create_verification_token(user.id)
    verify_url = f"{verify_base_url.rstrip('/')}/auth/verify?token={token}"
    await send_email(
        render_email(
            "verification",
            subject="Confirm your email",
            to=user.email,
            verify_url=verify_url,
        )
    )
