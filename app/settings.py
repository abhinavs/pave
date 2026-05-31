from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str
    use_sqlite: bool = False
    soniq_database_url: str | None = None

    # App
    app_name: str = "Pave"
    app_version: str = "0.0.1"
    debug: bool = False
    secret_key: str
    # Canonical public origin (e.g. https://usepave.dev). Outbound links in
    # email are built from this, not the inbound request Host, so a spoofed
    # Host header cannot redirect verification/reset links. Unset in dev: the
    # request origin is used as a fallback.
    base_url: str | None = None
    # NoDecode turns off pydantic-settings' default JSON decoding for list
    # fields, so a human-friendly comma-separated value (the form everyone
    # types in .env) is accepted instead of crashing on a JSON parse error.
    allowed_hosts: Annotated[list[str], NoDecode] = ["*"]

    # OAuth
    google_client_id: str | None = None
    google_client_secret: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None

    # Email — generic HTTP provider. When unset, email content is logged to console.
    email_api_key: str | None = None
    email_api_url: str | None = None
    email_from: str = "Pave <noreply@usepave.dev>"

    # Observability
    sentry_dsn: str | None = None
    enable_metrics: bool = False

    # Shared secret for verifying inbound webhook HMAC signatures. When set,
    # POST /webhooks/{slug} requires a matching X-Webhook-Signature. When unset,
    # ingestion is open only in debug; production rejects it until configured.
    webhook_secret: str | None = None

    # Deploy event sink
    webhooq_endpoint: str | None = None

    # Avatar uploads. The default writes under the served static tree so
    # the dev path needs no extra mount. Production deploys that want
    # persistent avatars should point this at a volume mounted outside
    # the release directory (otherwise a deploy will erase uploads).
    avatar_dir: str = "static/uploads/avatars"
    avatar_max_bytes: int = 4 * 1024 * 1024  # 4 MiB before resize

    # Logging
    log_level: str = "INFO"

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _split_allowed_hosts(cls, value: object) -> object:
        """Accept a comma-separated string ("a.com,b.com") or a real list."""
        if isinstance(value, str):
            return [host.strip() for host in value.split(",") if host.strip()]
        return value


# Placeholder secrets shipped in .env.example / .env. Convenient for local dev,
# catastrophic in production: they sign sessions, CSRF, and reset/verify tokens.
_KNOWN_WEAK_SECRET_KEYS = {
    "dev-secret-key-change-in-production",
    "test-secret-key",
    "change-me",
}
_MIN_SECRET_KEY_LENGTH = 32


def assert_secret_key_is_production_safe(s: "Settings") -> None:
    """Refuse to run in production with a guessable SECRET_KEY.

    Only enforced outside debug, so local dev keeps its convenient placeholder
    while a real deploy fails fast instead of signing tokens with a key that is
    public in the repo.
    """
    if s.debug:
        return
    if s.secret_key in _KNOWN_WEAK_SECRET_KEYS:
        raise RuntimeError(
            "SECRET_KEY is a known placeholder value. Generate a real one: "
            'python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    if len(s.secret_key) < _MIN_SECRET_KEY_LENGTH:
        raise RuntimeError(
            f"SECRET_KEY must be at least {_MIN_SECRET_KEY_LENGTH} characters "
            "in production."
        )


settings = Settings()
