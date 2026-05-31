"""Phase 4: the fabfile is the only task runner, so its shape is asserted.

These tests do not run any task. They check the contract AGENTS.md and the
build plan rely on: `fab validate` chains the five gates, the deploy health
check is the exact vrk pipeline, the deploy event uses httpx (not vrk), and
every local + remote task name is registered.
"""

import inspect

import fabfile

LOCAL_TASKS = {
    # Everyday local task running lives in the `pave` CLI (see test_cli.py).
    # Fabric keeps validate (the deploy gate) and the remote tasks below.
    "validate",
}
REMOTE_TASKS = {
    "deploy",
    "rollback",
    "logs",
    "ssh",
    "psql",
    "backup",
    "restore",
    "staging",
    "production",
}


def _task_names() -> set[str]:
    from invoke import Collection

    return set(Collection.from_module(fabfile).task_names)


def test_all_local_tasks_registered() -> None:
    assert LOCAL_TASKS <= _task_names()


def test_all_remote_tasks_registered() -> None:
    assert REMOTE_TASKS <= _task_names()


def test_validate_chains_css_migration_tests_mypy() -> None:
    src = inspect.getsource(fabfile.validate.body)
    assert "tailwindcss" in src  # css
    # The local checks are delegated to the pave CLI, not duplicated here.
    assert "pave migrate" in src  # migration
    assert "pave test" in src  # tests
    assert "pave typecheck" in src  # mypy


def test_deploy_runs_validate_before_any_ssh() -> None:
    src = inspect.getsource(fabfile.deploy.body)
    assert "validate(c" in src
    # validate appears before the first Connection use.
    assert src.index("validate(c") < src.index("_conn()")


def test_deploy_health_check_is_the_verbatim_vrk_pipeline() -> None:
    src = inspect.getsource(fabfile.deploy.body)
    assert "vrk coax --times 5 --backoff exp:200ms -- " in src
    assert "vrk grab https://" in src
    assert "/health" in src
    assert "vrk assert '.status == \\\"ok\\\"'" in src


def test_deploy_event_uses_httpx_not_vrk() -> None:
    src = inspect.getsource(fabfile._emit_deploy_event)
    assert "httpx.post" in src
    # It must not shell out at all (no vrk, no subprocess): httpx only.
    assert ".run(" not in src
    assert "subprocess" not in src
