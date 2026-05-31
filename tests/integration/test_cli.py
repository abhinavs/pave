"""The `pave` console script: the local CLI.

Local task running lives here, not in Fabric: Fabric is for SSH and the
deploy pipeline, and shelling local commands through it cost us a venv-PATH
bug we hit twice. These tests pin the contract: the CLI is registered with
Typer, every command the README/AGENTS document is present, the console
script is wired through pyproject, and `pave setup` is the Rails-style
bootstrap that creates the database before migrating.
"""

import inspect
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from app.cli import cli

runner = CliRunner()

LOCAL_COMMANDS = {
    "dev",
    "test",
    "lint",
    "fmt",
    "typecheck",
    "migrate",
    "migration",
    "downgrade",
    "setup",
    "shell",
    "worker",
    "soniq-setup",
}


def test_pave_help_lists_every_local_command() -> None:
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    out = result.stdout
    for cmd in LOCAL_COMMANDS:
        assert cmd in out, f"command {cmd!r} missing from `pave --help`"


def test_pave_console_script_is_declared_in_pyproject() -> None:
    # Without [project.scripts] pip install -e . drops no `pave` shim into
    # .venv/bin and the whole CLI is unreachable. Pin the entry here.
    pyproject = tomllib.loads(
        (Path(__file__).parents[2] / "pyproject.toml").read_text()
    )
    assert pyproject["project"]["scripts"]["pave"] == "app.cli:cli"


def test_setup_creates_db_then_migrates_then_seeds_soniq() -> None:
    from app.cli import setup

    src = inspect.getsource(setup)
    # Rails-style one-shot. createdb is guarded by use_sqlite (the file path
    # needs no createdb), then schema migrations, then the Soniq tables.
    assert "createdb" in src
    assert "use_sqlite" in src
    assert "migrate(" in src
    assert "soniq_setup(" in src
    assert (
        src.index("createdb")
        < src.index("migrate(")
        < src.index("soniq_setup(")
    )
