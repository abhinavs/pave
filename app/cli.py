"""The Pave CLI: every local task is a `pave` subcommand.

This is the home for day-to-day commands a developer types. Fabric (see
fabfile.py) keeps `validate` (the deploy gate) and the remote tasks where
SSH and host targeting actually matter; everything local lives here because:

  * It runs inside the active venv: no fab-spawns-bash, no missing PATH.
  * One Python process per command: faster than fab's shell hop.
  * Commands can reuse each other as plain function calls (see `setup`).
  * Typer gives a polished `--help` and discoverable subcommands.

Wiring: `[project.scripts] pave = "app.cli:cli"` in pyproject.toml. After
`pip install -e .` the `.venv/bin/pave` shim points back at this module.

Imports inside command bodies are deliberate. The CLI's `--help` should
return in milliseconds, so we do not pull in the database engine, settings,
IPython, or the Soniq app at module-import time. Only the command actually
invoked pays for its own dependencies.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer

# The venv's bin/ directory (next to whatever Python is running this CLI).
# We resolve subprocess arg-zero through this first so `pave dev` works
# whether or not the shell has the venv activated - the friction that made
# `fab dev` brittle in the first place (honcho missing from /bin/bash PATH).
_VENV_BIN = Path(sys.executable).parent

cli = typer.Typer(
    add_completion=False,
    help="Pave local commands. For remote tasks see `fab --list`.",
    no_args_is_help=True,
)


def _run(*args: str) -> None:
    """Run a subprocess and exit non-zero if it fails. No shell, never.

    Arg zero is resolved against the venv's bin/ first so tools installed
    in the project venv (honcho, pytest, ruff, mypy, alembic) are found
    even when the shell has not activated the venv. System tools that are
    not in the venv (createdb, git) fall through to a normal PATH lookup.
    """
    cmd = list(args)
    venv_candidate = _VENV_BIN / cmd[0]
    if venv_candidate.exists():
        cmd[0] = str(venv_candidate)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)


# --- dev loop --------------------------------------------------------------


@cli.command()
def dev() -> None:
    """Run uvicorn + the tailwind watcher together via honcho (Procfile)."""
    _run("honcho", "start")


@cli.command()
def test() -> None:
    """Run the full test suite (pytest -q)."""
    _run("pytest", "-q")


@cli.command()
def lint() -> None:
    """Ruff check."""
    _run("ruff", "check", ".")


@cli.command()
def fmt() -> None:
    """Ruff format."""
    _run("ruff", "format", ".")


@cli.command()
def typecheck() -> None:
    """Mypy on app/."""
    _run("mypy", "app/")


# --- schema -----------------------------------------------------------------


@cli.command()
def migrate() -> None:
    """Apply migrations locally (alembic upgrade head)."""
    _run("alembic", "upgrade", "head")


@cli.command("check-migrations")
def check_migrations() -> None:
    """Verify the migration chain applies cleanly, without mutating any real db.

    The deploy gate must never run `alembic upgrade` against the operator's
    configured DATABASE_URL. This applies every migration to a throwaway
    SQLite database in a temp dir, then discards it, so a broken migration is
    caught before deploy with no side effects.
    """
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "migration-check.db"
        env = {
            **os.environ,
            # USE_SQLITE=false so _build_url passes the sqlite URL through as-is.
            "USE_SQLITE": "false",
            "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        }
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], env=env
        )
        if result.returncode != 0:
            raise typer.Exit(code=result.returncode)


@cli.command()
def migration(message: str = typer.Option(..., "--message", "-m")) -> None:
    """Autogenerate a migration. Review the generated file before `pave migrate`."""
    _run("alembic", "revision", "--autogenerate", "-m", message)


@cli.command()
def downgrade(step: str = "-1") -> None:
    """Roll a migration back (default one step) to test the downgrade."""
    _run("alembic", "downgrade", step)


@cli.command("check-env")
def check_env(env_file: str = ".env") -> None:
    """Verify every variable marked `required` in .env.schema is actually set.

    .env.schema is the contract; this is what makes it more than a comment.
    Reads the schema, then checks the process environment plus the given env
    file, and exits non-zero listing anything missing, so a deploy or CI step
    can gate on it.
    """
    import os

    def _keys(path: Path) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            pairs.append((key.strip(), value.strip()))
        return pairs

    schema = Path(".env.schema")
    if not schema.exists():
        typer.echo("check-env: .env.schema not found")
        raise typer.Exit(code=1)

    present = dict(os.environ)
    env_path = Path(env_file)
    if env_path.exists():
        for key, value in _keys(env_path):
            present.setdefault(key, value)

    required = [key for key, spec in _keys(schema) if spec == "required"]
    missing = [key for key in required if not present.get(key)]
    if missing:
        typer.echo(f"check-env: missing required variables: {', '.join(missing)}")
        raise typer.Exit(code=1)
    typer.echo("check-env: all required variables are set")


@cli.command()
def setup() -> None:
    """Rails-style one-shot local bootstrap: create the database, migrate,
    then create the Soniq tables.

    Idempotent. On Postgres it creates the database named in DATABASE_URL
    ("already exists" is expected on a re-run and tolerated); under
    USE_SQLITE the file is created on first connect, so only the schema
    steps run. Then alembic, then Soniq's tables.
    """
    from urllib.parse import urlparse

    from app.settings import settings

    if not settings.use_sqlite:
        db_name = urlparse(settings.database_url).path.lstrip("/")
        # `createdb` exits non-zero when the database already exists; that
        # is expected on a re-run, so we report and continue rather than aborting.
        result = subprocess.run(["createdb", db_name])
        if result.returncode != 0:
            typer.echo(f"createdb: skipped (database {db_name!r} likely exists)")

    migrate()
    soniq_setup()


# --- ops --------------------------------------------------------------------


@cli.command()
def shell() -> None:
    """Open an IPython shell with the app, models and session factory loaded."""
    import IPython

    from app import models
    from app.database import AsyncSessionLocal, engine
    from app.jobs import soniq
    from app.settings import settings

    IPython.start_ipython(  # type: ignore[no-untyped-call]
        argv=[],
        user_ns={
            "settings": settings,
            "engine": engine,
            "AsyncSessionLocal": AsyncSessionLocal,
            "models": models,
            "soniq": soniq,
        },
        banner1="Pave shell: settings, engine, AsyncSessionLocal, models, soniq",
    )


@cli.command()
def worker(concurrency: int = 4, queues: str | None = None) -> None:
    """Run a Soniq worker. Jobs are discovered by importing `app.jobs`."""
    import asyncio

    from app.jobs import soniq

    queue_list = [q.strip() for q in queues.split(",")] if queues else None
    asyncio.run(soniq.run_worker(concurrency=concurrency, queues=queue_list))


@cli.command("soniq-setup")
def soniq_setup() -> None:
    """Create the Soniq queue tables. Idempotent: safe to run repeatedly."""
    import asyncio

    # Import-guarded: a misconfigured queue URL should report cleanly, not
    # crash before Typer can print anything useful.
    try:
        from app.jobs import soniq
    except Exception as exc:
        typer.echo(f"Could not import the Soniq app: {exc}")
        raise typer.Exit(code=1) from exc

    typer.echo("Setting up Soniq queue tables...")
    asyncio.run(soniq.setup())
    typer.echo("Soniq is ready.")


if __name__ == "__main__":
    # Falling back to `python -m app.cli` works without the console script
    # entry being installed, which is handy in fresh checkouts.
    sys.exit(cli())
