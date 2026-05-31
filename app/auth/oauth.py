"""OAuth: Authlib client registry plus the find-or-create that backs callbacks.

The find-or-create is deliberately a plain function, not buried in a route, so
it is unit-testable without standing up a provider. Its one job is to make
sign-in idempotent: signing in twice, or signing in after a password signup
with the same email, must never create a second account.
"""

from datetime import UTC, datetime

from authlib.integrations.starlette_client import (  # type: ignore[import-untyped]
    OAuth,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.settings import settings

oauth = OAuth()

if settings.google_client_id and settings.google_client_secret:
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url=(
            "https://accounts.google.com/.well-known/openid-configuration"
        ),
        client_kwargs={"scope": "openid email profile"},
    )

if settings.github_client_id and settings.github_client_secret:
    oauth.register(
        name="github",
        client_id=settings.github_client_id,
        client_secret=settings.github_client_secret,
        access_token_url="https://github.com/login/oauth/access_token",
        authorize_url="https://github.com/login/oauth/authorize",
        api_base_url="https://api.github.com/",
        client_kwargs={"scope": "read:user user:email"},
    )


async def find_or_create_oauth_user(
    db: AsyncSession,
    *,
    provider: str,
    provider_id: str,
    email: str | None,
    name: str,
    avatar_url: str | None,
) -> User:
    """Resolve an OAuth identity to exactly one local user.

    Match order: the (provider, provider_id) pair first, then the email. Only
    when neither matches do we create. GitHub may withhold the email, so a
    None email is expected and simply skips the email match.
    """
    by_provider = await db.execute(
        select(User).where(
            User.provider == provider, User.provider_id == provider_id
        )
    )
    user = by_provider.scalar_one_or_none()
    if user is not None:
        return user

    if email:
        by_email = await db.execute(select(User).where(User.email == email))
        user = by_email.scalar_one_or_none()
        if user is not None:
            # Link the OAuth identity onto the existing account in place.
            user.provider = user.provider or provider
            user.provider_id = user.provider_id or provider_id
            if not user.avatar_url:
                user.avatar_url = avatar_url
            if user.email_verified_at is None:
                user.email_verified_at = datetime.now(UTC)
            await db.commit()
            await db.refresh(user)
            return user

    user = User(
        name=name,
        # No provider email: synthesize a stable, unique placeholder so the
        # NOT NULL / UNIQUE email column still holds.
        email=email or f"{provider}-{provider_id}@users.noreply.local",
        provider=provider,
        provider_id=provider_id,
        avatar_url=avatar_url,
        email_verified_at=datetime.now(UTC),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
