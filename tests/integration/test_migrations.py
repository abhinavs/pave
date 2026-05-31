"""Alembic must apply cleanly and reverse cleanly on a scratch database."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _alembic(args: list[str], db_url: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "USE_SQLITE": "false",  # so _build_url passes DATABASE_URL through unchanged
        "DATABASE_URL": db_url,
        "SECRET_KEY": "test-secret-key",
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_migrations_round_trip(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'm.db'}"

    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, f"upgrade failed:\n{up.stderr}"

    down = _alembic(["downgrade", "base"], db_url)
    assert down.returncode == 0, f"downgrade failed:\n{down.stderr}"


def test_check_migrations_does_not_touch_database_url() -> None:
    """`pave check-migrations` verifies the chain against a throwaway sqlite
    db, so it succeeds even when DATABASE_URL points at an unreachable host.
    That is the whole point: the deploy gate must never mutate a real db."""
    env = {
        **os.environ,
        "USE_SQLITE": "false",
        # Deliberately unreachable: if the command touched this, it would fail.
        "DATABASE_URL": "postgresql://nobody@127.0.0.1:1/does_not_exist",
        "SECRET_KEY": "test-secret-key",
    }
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "check-migrations"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"check-migrations failed:\n{result.stderr}"
