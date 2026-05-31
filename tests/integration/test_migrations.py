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
