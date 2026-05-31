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
    # A dirty tree would make the release hash misrepresent what shipped...
    assert "git status --porcelain" in src
    # ...and an unpushed HEAD means shipping a commit no one else (or CI) has.
    assert "--contains HEAD" in src or "origin" in src


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
    # Each deploy builds its own venv; without pruning the disk fills up.
    assert "KEEP_RELEASES" in src or "head -n -" in src
    assert fabfile.KEEP_RELEASES >= 2  # always keep a rollback target


def test_deploy_ships_a_clean_tree_not_the_working_dir() -> None:
    src = inspect.getsource(fabfile.deploy.body)
    # Honour .gitignore so local .env secrets and caches never ship, and
    # --delete so a reused release dir cannot carry stale files.
    assert ".gitignore" in src
    assert "--delete" in src
    # app.css is a gitignored build artifact; validate builds it fresh, so the
    # rsync must force-include it (ahead of the .gitignore filter) or the
    # server, which has no Tailwind, would ship with no CSS.
    assert "+ /static/css/app.css" in src


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
