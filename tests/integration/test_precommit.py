"""Annotation and ruff-format run as pre-commit hooks, not Fabric
tasks, because they rewrite files on the way into a commit rather than on
demand.

These tests do not invoke pre-commit. They pin the hook contract: the
dogfooded sqlalchemy-annotate tool runs against the real models package at the
production dialect, ruff comes from the official mirror, and the three hooks
fire in the one order in which the tools converge in a single pass
(annotate -> ruff --fix -> ruff-format).
"""

from pathlib import Path

import yaml

CONFIG = Path(__file__).parents[2] / ".pre-commit-config.yaml"


def _config() -> dict:
    return yaml.safe_load(CONFIG.read_text())


def test_precommit_config_exists() -> None:
    assert CONFIG.is_file()


def test_annotate_hook_drives_sqlalchemy_annotate() -> None:
    repos = _config()["repos"]
    local = next(r for r in repos if r["repo"] == "local")
    hook = next(h for h in local["hooks"] if h["id"] == "sqlalchemy-annotate")

    # The dogfooded tool, the real models package, and the production
    # (Postgres) dialect so the annotation is not the SQLite fallback type.
    assert "sqlalchemy-annotate generate" in hook["entry"]
    assert "--models app.models" in hook["entry"]
    assert "postgresql" in hook["entry"]

    # It imports the models package and takes a dotted --models argument, so
    # it must use the project environment and never receive file paths.
    assert hook["language"] == "system"
    assert hook["pass_filenames"] is False
    assert "app/models" in hook["files"]


def test_ruff_hooks_come_from_the_official_mirror() -> None:
    repos = _config()["repos"]
    ruff_repo = next(
        r for r in repos if r["repo"] == "https://github.com/astral-sh/ruff-pre-commit"
    )
    ids = [h["id"] for h in ruff_repo["hooks"]]
    assert "ruff" in ids
    assert "ruff-format" in ids

    lint = next(h for h in ruff_repo["hooks"] if h["id"] == "ruff")
    assert "--fix" in lint["args"]


def test_mypy_hook_type_checks_app() -> None:
    repos = _config()["repos"]
    hooks = [h for repo in repos for h in repo["hooks"]]
    mypy = next(h for h in hooks if h["id"] == "mypy")

    # Strict type check on app/, run from the project env so it sees the same
    # dependencies and stubs `pave typecheck` does.
    assert "mypy app/" in mypy["entry"]
    assert mypy["language"] == "system"
    assert mypy["pass_filenames"] is False


def test_standard_hygiene_hooks_present() -> None:
    repos = _config()["repos"]
    hygiene = next(
        r
        for r in repos
        if r["repo"] == "https://github.com/pre-commit/pre-commit-hooks"
    )
    ids = {h["id"] for h in hygiene["hooks"]}
    expected = {
        "trailing-whitespace",
        "end-of-file-fixer",
        "check-yaml",
        "check-toml",
        "check-added-large-files",
        "check-merge-conflict",
    }
    assert expected <= ids, f"missing hygiene hooks: {expected - ids}"


def test_hook_order_is_annotate_then_lint_then_format() -> None:
    # The tools converge in exactly one pass only in this order: annotate
    # writes a schema block whose import spacing ruff's isort would reject,
    # `ruff --fix` settles I001, and `ruff-format` finalises the layout.
    order = [h["id"] for repo in _config()["repos"] for h in repo["hooks"]]
    assert order.index("sqlalchemy-annotate") < order.index("ruff")
    assert order.index("ruff") < order.index("ruff-format")
