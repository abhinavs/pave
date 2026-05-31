"""Structural guarantee tests.

These assert Pave's invariants hold regardless of feature code. They are
extended in later phases (schema leak surface, etc.) but every assertion here
must always pass.
"""

import ast
from pathlib import Path

# tests/integration/test_template.py -> project root is three parents up
ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"

REQUIRED_FILES = [
    ".gitignore",
    ".env.example",
    ".env.schema",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "AGENTS.md",
    "CLAUDE.md",
    "app/settings.py",
    "app/database.py",
    "app/main.py",
    "app/routers/health.py",
]


def test_required_files_exist() -> None:
    missing = [f for f in REQUIRED_FILES if not (ROOT / f).exists()]
    assert not missing, f"missing required files: {missing}"


def _orm_model_names() -> set[str]:
    names: set[str] = set()
    models_dir = APP / "models"
    if not models_dir.exists():
        return names
    for path in models_dir.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                names.add(node.name)
    return names


def test_no_orm_model_used_as_response_model() -> None:
    """Routers must never pass an app.models class as response_model."""
    orm_names = _orm_model_names()
    if not orm_names:
        return  # no models yet (pre Phase 2) - nothing to check
    routers = APP / "routers"
    offenders: list[str] = []
    for path in routers.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "response_model":
                v = node.value
                if isinstance(v, ast.Name) and v.id in orm_names:
                    offenders.append(f"{path.name}: response_model={v.id}")
    assert not offenders, f"ORM model used as response_model: {offenders}"


SECRET_FIELDS = {"password_hash", "provider_id"}


def test_no_secret_fields_in_any_schema() -> None:
    """No schema in app/schemas/ may carry an internal or secret field.

    Output schemas are the response surface; an annotated `password_hash` or
    `provider_id` anywhere here is a leak waiting to happen, so the invariant
    is enforced for every schema class, input or output.
    """
    schemas_dir = APP / "schemas"
    if not schemas_dir.exists():
        return  # no schemas yet - nothing to check
    offenders: list[str] = []
    for path in schemas_dir.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(
                    stmt.target, ast.Name
                ):
                    if stmt.target.id in SECRET_FIELDS:
                        offenders.append(
                            f"{path.name}:{node.name}.{stmt.target.id}"
                        )
    assert not offenders, f"secret field in schema: {offenders}"
