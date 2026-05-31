"""Settings parsing edge cases.

ALLOWED_HOSTS is a list field. pydantic-settings JSON-decodes list fields from
env vars by default, so a plain value like `*` or `a.com,b.com` used to crash
startup with a SettingsError before anything ran. These tests pin the
comma-separated form (what a human actually types in .env) as supported.
"""

import pytest

from app.settings import (
    Settings,
    assert_secret_key_is_production_safe,
)


def _settings(monkeypatch: pytest.MonkeyPatch, *, debug: bool, secret: str) -> Settings:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SECRET_KEY", secret)
    monkeypatch.setenv("DEBUG", "true" if debug else "false")
    return Settings(_env_file=None)


def test_weak_secret_key_allowed_in_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    # Local dev keeps a convenient placeholder; the guard only bites in prod.
    s = _settings(monkeypatch, debug=True, secret="dev-secret-key-change-in-production")
    assert_secret_key_is_production_safe(s)  # does not raise


def test_placeholder_secret_key_rejected_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _settings(
        monkeypatch, debug=False, secret="dev-secret-key-change-in-production"
    )
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        assert_secret_key_is_production_safe(s)


def test_short_secret_key_rejected_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _settings(monkeypatch, debug=False, secret="too-short")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        assert_secret_key_is_production_safe(s)


def test_strong_secret_key_passes_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _settings(monkeypatch, debug=False, secret="x" * 48)
    assert_secret_key_is_production_safe(s)  # does not raise


def _make(monkeypatch: pytest.MonkeyPatch, value: str) -> Settings:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    monkeypatch.setenv("ALLOWED_HOSTS", value)
    # _env_file=None so the repo .env never shadows what the test sets.
    return Settings(_env_file=None)


def test_allowed_hosts_wildcard_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _make(monkeypatch, "*").allowed_hosts == ["*"]


def test_allowed_hosts_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _make(monkeypatch, "usepave.dev,www.usepave.dev")
    assert s.allowed_hosts == ["usepave.dev", "www.usepave.dev"]


def test_allowed_hosts_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _make(monkeypatch, "  a.com , b.com ")
    assert s.allowed_hosts == ["a.com", "b.com"]


def test_allowed_hosts_single_value(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _make(monkeypatch, "usepave.dev").allowed_hosts == ["usepave.dev"]
