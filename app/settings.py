from pydantic_settings import BaseSettings, SettingsConfigDict


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
    allowed_hosts: list[str] = ["*"]

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


settings = Settings()
