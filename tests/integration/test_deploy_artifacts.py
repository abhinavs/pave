"""The deploy artifacts and hardening tasks are shipped, not live-run.

These tests never touch a server. They assert the files in deploy/ exist with
the shape DEPLOY.md and fabfile.py rely on (the same DEPLOY_USER, APP_DIR and
service names the fabfile uses), and that every optional `fab setup-*` task is
registered so it is discoverable via `fab --list`.
"""

import re
from pathlib import Path

import fabfile

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
DOCS = ROOT / "docs"

# The single source of truth for where the env file lives on the server. It
# must sit OUTSIDE the release directories (which each deploy replaces), so it
# is shared and stable across releases.
ENV_FILE_PATH = "/srv/pave/shared/.env.production"

SETUP_TASKS = {
    "setup-firewall",
    "setup-fail2ban",
    "setup-tls",
    "setup-backups",
    "setup-ssh",
    "setup-auto-updates",
    "setup-swap",
    "setup-log-rotation",
    "setup-monitoring",
    "setup-server",
}


def _task_names() -> set[str]:
    from invoke import Collection

    return set(Collection.from_module(fabfile).task_names)


def _read(name: str) -> str:
    path = DEPLOY / name
    assert path.is_file(), f"missing deploy artifact: {name}"
    return path.read_text()


# --- nginx ----------------------------------------------------------------


def test_nginx_conf_has_domain_placeholder_and_proxies() -> None:
    conf = _read("nginx.conf")
    assert "{{domain}}" in conf  # filled in per environment, not hard-coded
    assert "server_name" in conf
    assert "proxy_pass" in conf
    assert "location /" in conf
    assert "/health" in conf  # the health endpoint is reachable through nginx


def test_nginx_rate_limiting_is_enabled() -> None:
    conf = _read("nginx.conf")
    # Both halves of the rate limit must be active: the zone definition and
    # the limit_req in the proxied location.
    active = [
        ln
        for ln in conf.splitlines()
        if "limit_req" in ln and not ln.lstrip().startswith("#")
    ]
    assert any("limit_req_zone" in ln for ln in active), "rate-limit zone not enabled"
    assert any("limit_req " in ln or "limit_req\t" in ln for ln in active), (
        "limit_req not enabled in a location block"
    )


def test_nginx_sets_hsts_and_csp() -> None:
    conf = _read("nginx.conf")
    assert "Strict-Transport-Security" in conf
    assert "Content-Security-Policy" in conf


def test_ci_mirrors_validate_css_build() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    # validate builds CSS before tests; CI claims parity, so it must too.
    assert "tailwindcss" in ci, "CI does not build CSS like fab validate"


# --- systemd units --------------------------------------------------------


def test_api_service_runs_gunicorn_uvicorn_worker() -> None:
    unit = _read("pave-api.service")
    assert "[Unit]" in unit and "[Service]" in unit and "[Install]" in unit
    assert "ExecStart=" in unit
    assert "gunicorn" in unit
    assert "UvicornWorker" in unit
    assert "User=deploy" in unit  # matches fabfile DEPLOY_USER
    assert "/srv/pave/current" in unit  # matches fabfile CURRENT
    assert "WantedBy=multi-user.target" in unit


def test_worker_service_runs_the_soniq_worker() -> None:
    unit = _read("pave-worker.service")
    assert "[Service]" in unit and "[Install]" in unit
    assert "ExecStart=" in unit
    assert "worker" in unit  # `python -m app.cli worker`
    assert "User=deploy" in unit
    assert "WantedBy=multi-user.target" in unit


def test_units_drain_gracefully_on_a_deploy_restart() -> None:
    # A deploy restarts both services; neither may hard-kill live work. The API
    # finishes in-flight requests (gunicorn --graceful-timeout) and the worker
    # finishes its current job, each bounded by TimeoutStopSec so a stuck
    # process cannot wedge the deploy.
    api = _read("pave-api.service")
    assert "--graceful-timeout" in api
    assert "TimeoutStopSec=" in api
    worker = _read("pave-worker.service")
    assert "TimeoutStopSec=" in worker


def test_units_are_hardened_with_writable_shared_dir() -> None:
    # ProtectSystem=strict makes the FS read-only except the explicit
    # ReadWritePaths; uploads live under /srv/pave/shared so that must be
    # writable. ProtectHome keeps /home off-limits.
    for unit in ("pave-api.service", "pave-worker.service"):
        u = _read(unit)
        assert "ProtectSystem=strict" in u, f"{unit} not hardened to strict"
        assert "ProtectHome=" in u, f"{unit} missing ProtectHome"
        assert "/srv/pave/shared" in u, f"{unit} cannot write the shared dir"


# --- env file path consistency --------------------------------------------


def _env_file_in_unit(unit_name: str) -> str:
    unit = _read(unit_name)
    match = re.search(r"^EnvironmentFile=(.+)$", unit, re.MULTILINE)
    assert match, f"{unit_name} declares no EnvironmentFile"
    return match.group(1).strip()


def test_units_load_env_from_stable_shared_path() -> None:
    # A release-relative path (/srv/pave/current/...) is wrong: every deploy
    # swaps in a fresh release dir, so the env file would have to be re-placed
    # each time, and a missing EnvironmentFile is a fatal systemd start error.
    for unit in ("pave-api.service", "pave-worker.service"):
        path = _env_file_in_unit(unit)
        assert path == ENV_FILE_PATH, f"{unit} EnvironmentFile={path}"
        assert "/current/" not in path, f"{unit} env path is release-relative"


def test_backup_script_sources_the_same_env_path() -> None:
    # backup.sh builds the path from ${APP_DIR}, so match the shared suffix
    # rather than the fully-resolved literal.
    script = _read("backup.sh")
    assert "shared/.env.production" in script, "backup.sh must use the shared env path"
    assert "/current/.env.production" not in script


def test_docs_point_at_the_shared_env_path() -> None:
    for doc in ("getting-started.md", "deploy.md"):
        text = (DOCS / doc).read_text()
        if ".env.production" not in text:
            continue
        assert ENV_FILE_PATH in text, f"{doc} must reference {ENV_FILE_PATH}"


# --- backups --------------------------------------------------------------


def test_backup_script_is_a_safe_bash_pg_dump() -> None:
    script = _read("backup.sh")
    assert script.startswith("#!")
    assert "bash" in script.splitlines()[0]
    assert "set -euo pipefail" in script
    assert "pg_dump" in script
    assert "gzip" in script


def test_backup_timer_runs_on_a_schedule() -> None:
    timer = _read("backup.timer")
    assert "[Timer]" in timer
    assert "OnCalendar=" in timer
    assert "WantedBy=timers.target" in timer


def test_backup_service_is_oneshot_and_calls_the_script() -> None:
    svc = _read("backup.service")
    assert "[Service]" in svc
    assert "Type=oneshot" in svc
    assert "backup.sh" in svc


# --- fab setup-* tasks ----------------------------------------------------


def test_all_setup_tasks_registered() -> None:
    assert SETUP_TASKS <= _task_names()
