"""Structural guarantee tests.

These assert Pave's invariants hold regardless of feature code. Every
assertion here must always pass.
"""

import ast
import re
from pathlib import Path

# tests/integration/test_template.py -> project root is three parents up
ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"

# Settings fields that are app constants, not deploy-time env config, so they
# are intentionally absent from .env.example / .env.schema.
_INTERNAL_SETTINGS = {"app_name", "app_version"}


def _settings_env_keys() -> set[str]:
    """Every Settings field name, upper-cased, that is part of the env contract."""
    tree = ast.parse((APP / "settings.py").read_text())
    cls = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "Settings"
    )
    fields = {
        stmt.target.id
        for stmt in cls.body
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
    }
    return {f.upper() for f in fields - _INTERNAL_SETTINGS}


def _env_file_keys(name: str) -> set[str]:
    keys: set[str] = set()
    for line in (ROOT / name).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.add(line.split("=", 1)[0].strip())
    return keys


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
        return  # no models yet - nothing to check
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


def test_env_example_and_schema_have_the_same_keys() -> None:
    """The two env docs must stay in lockstep: AGENTS.md promises every setting
    lives in both .env.example and .env.schema."""
    example = _env_file_keys(".env.example")
    schema = _env_file_keys(".env.schema")
    assert example == schema, (
        f"only in .env.example: {example - schema}; "
        f"only in .env.schema: {schema - example}"
    )


def test_every_setting_is_documented_in_env_files() -> None:
    """Every Settings field (minus internal constants) appears in both env
    files, and neither file documents a key with no backing Settings field."""
    settings_keys = _settings_env_keys()
    example = _env_file_keys(".env.example")
    schema = _env_file_keys(".env.schema")

    assert settings_keys <= example, (
        f"undocumented in .env.example: {settings_keys - example}"
    )
    assert settings_keys <= schema, (
        f"undocumented in .env.schema: {settings_keys - schema}"
    )
    assert example <= settings_keys, (
        f"orphan in .env.example: {example - settings_keys}"
    )
    assert schema <= settings_keys, f"orphan in .env.schema: {schema - settings_keys}"


def test_runtime_requirements_cover_direct_imports() -> None:
    """A package the app imports at runtime must be a direct runtime dep, not
    a transitive or dev-only one."""
    reqs = (ROOT / "requirements.txt").read_text()
    # app/ imports pydantic directly (settings, schemas, validators), so it
    # cannot rely on pydantic-settings pulling it in transitively.
    assert re.search(r"(?m)^pydantic\b", reqs), "pydantic must be a runtime dep"
    # USE_SQLITE is a documented runtime option, so its driver must ship in a
    # production (requirements.txt-only) install too.
    assert "aiosqlite" in reqs, "aiosqlite must ship so USE_SQLITE works in prod"


def test_docs_do_not_reference_nonexistent_modules() -> None:
    """Doc examples must import from real modules (the email helper lives at
    app.email, not app.services.email)."""
    for doc in (ROOT / "docs").glob("*.md"):
        assert "app.services.email" not in doc.read_text(), (
            f"stale import in {doc.name}"
        )


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
                        offenders.append(f"{path.name}:{node.name}.{stmt.target.id}")
    assert not offenders, f"secret field in schema: {offenders}"
