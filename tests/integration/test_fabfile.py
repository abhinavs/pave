"""The fabfile is the only task runner, so its shape is asserted.

These tests do not run any task. They check the contract the deploy pipeline
relies on: `fab validate` chains the five gates, the deploy health
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
    "rebuild-venv",
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


def test_bare_task_falls_back_to_the_default_environment() -> None:
    # A bare `fab deploy` (no `staging`/`production` selector) targets
    # DEFAULT_ENV instead of erroring, and that default must be a real target.
    assert fabfile.DEFAULT_ENV in fabfile._TARGETS
    fabfile._SELECTED.clear()
    try:
        assert fabfile._target() == fabfile._TARGETS[fabfile.DEFAULT_ENV]
    finally:
        fabfile._SELECTED.clear()


def test_selecting_an_environment_overrides_the_default() -> None:
    fabfile._SELECTED.clear()
    try:
        fabfile.staging.body(None)  # .body is the unwrapped function
        assert fabfile._target()["host"] == fabfile._TARGETS["staging"]["host"]
    finally:
        fabfile._SELECTED.clear()


def test_validate_chains_css_migration_tests_mypy() -> None:
    src = inspect.getsource(fabfile.validate.body)
    assert "tailwindcss" in src  # css
    # The local checks are delegated to the pave CLI, not duplicated here.
    assert "pave check-migrations" in src  # migrations verified, not applied
    assert "pave test" in src  # tests
    assert "pave typecheck" in src  # mypy


def test_validate_does_not_mutate_a_real_database() -> None:
    # The gate must never run `pave migrate` (which applies migrations to
    # whatever DATABASE_URL the operator has configured). It verifies the
    # migration chain against a throwaway database instead.
    src = inspect.getsource(fabfile.validate.body)
    assert "pave migrate" not in src


def test_deploy_refuses_dirty_or_unpushed_source() -> None:
    src = inspect.getsource(fabfile.deploy.body)
    # A dirty tree means the tested code is not what is committed...
    assert "git status --porcelain" in src
    # ...and the server ships origin/<branch>, so local HEAD must equal that
    # branch tip or it would deploy a different commit than the one validated.
    assert "origin/" in src and "rev-parse HEAD" in src


def test_restore_is_transactional_and_guarded() -> None:
    src = inspect.getsource(fabfile.restore.body)
    # A bad restore mid-incident must not half-apply or run unconfirmed.
    assert "--single-transaction" in src
    assert "yes" in src  # explicit confirmation flag
    assert "backup(" in src  # safety backup before clobbering


def test_deploy_verifies_worker_is_live() -> None:
    src = inspect.getsource(fabfile.deploy.body)
    # The health check only probes the API; a deploy must also confirm the
    # worker actually came up, or it can ship a dead job queue as "green".
    assert "is-active" in src and "pave-worker" in src


def test_deploy_persists_uploads_via_shared_symlink() -> None:
    src = inspect.getsource(fabfile.deploy.body)
    # Uploads must survive a deploy: each release's static/uploads is a symlink
    # into the persistent shared dir, not a real (wiped-every-deploy) directory.
    assert "shared/uploads" in src
    assert "static/uploads" in src
    assert "ln -sfn" in src


def test_deploy_prunes_old_releases() -> None:
    src = inspect.getsource(fabfile.deploy.body)
    # Releases accumulate even though the venv is shared; without pruning the
    # disk fills up.
    assert "KEEP_RELEASES" in src or "head -n -" in src
    assert fabfile.KEEP_RELEASES >= 2  # always keep a rollback target


def test_deploy_ships_a_clean_tree_not_the_working_dir() -> None:
    src = inspect.getsource(fabfile.deploy.body)
    # The snapshot is a `git archive` of origin/<branch>, which exports only
    # tracked files: gitignored secrets (.env), the dev db, and caches are
    # untracked, so they cannot ride along. No rsync, no .gitignore filter.
    assert "git -C" in src and "archive" in src
    assert "rsync" not in src


def test_deploy_builds_css_on_the_server() -> None:
    src = inspect.getsource(fabfile.deploy.body)
    # app.css is a gitignored build artifact, so the archive carries none; the
    # server rebuilds it with the pinned Tailwind binary, or it would ship
    # with no CSS.
    assert "tailwindcss" in src
    assert "static/css/app.css" in src


def test_deploy_uses_the_shared_venv_not_a_release_venv() -> None:
    src = inspect.getsource(fabfile.deploy.body)
    # Deploys reuse one venv for speed; the deploy must not build a per-release
    # one. rebuild-venv is the escape hatch for a stale shared venv.
    assert "SHARED_VENV" in src
    assert "python -m venv .venv" not in src


def test_rebuild_venv_recreates_from_scratch() -> None:
    src = inspect.getsource(fabfile.rebuild_venv.body)
    # A removed dependency only clears on a from-scratch rebuild, so it must rm
    # the old venv before recreating and reinstalling.
    assert "rm -rf" in src and "SHARED_VENV" in src
    assert "pip install" in src


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


def test_remote_db_tasks_source_the_env_file() -> None:
    # psql/backup/restore run in a bare login shell where DATABASE_URL is unset
    # (systemd loads the env file, the shell does not), so each must source it
    # via the _with_env wrapper.
    for task in (fabfile.psql, fabfile.backup, fabfile.restore):
        src = inspect.getsource(task.body)
        assert "_with_env(" in src, f"{task.__name__} does not source the env file"
    # And the wrapper actually sources the shared env file.
    helper = inspect.getsource(fabfile._with_env)
    assert "SHARED_ENV" in helper
    assert ".env.production" in fabfile.SHARED_ENV


def test_rollback_picks_previous_by_name_not_mtime() -> None:
    src = inspect.getsource(fabfile.rollback.body)
    # mtime ordering (ls -t) is reordered by rsync/restore; release names are
    # timestamp-prefixed, so a name sort is the stable chronological order.
    assert "ls -1dt" not in src, "rollback must not order releases by mtime"
    assert "sort" in src


def test_deploy_event_uses_httpx_not_vrk() -> None:
    src = inspect.getsource(fabfile._emit_deploy_event)
    assert "httpx.post" in src
    # It must not shell out at all (no vrk, no subprocess): httpx only.
    assert ".run(" not in src
    assert "subprocess" not in src


def test_deploy_event_failure_is_logged_not_swallowed() -> None:
    src = inspect.getsource(fabfile._emit_deploy_event)
    # The webhook is best-effort, but a misconfigured endpoint must be visible,
    # not silently swallowed forever.
    assert "except Exception" in src
    assert "print(" in src
