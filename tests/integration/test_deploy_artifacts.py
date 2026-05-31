"""Phase 7: the deploy artifacts and hardening tasks are shipped, not live-run.

These tests never touch a server. They assert the files in deploy/ exist with
the shape DEPLOY.md and fabfile.py rely on (the same DEPLOY_USER, APP_DIR and
service names the fabfile uses), and that every optional `fab setup-*` task is
registered so it is discoverable via `fab --list`.
"""

from pathlib import Path

import fabfile

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"

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


def test_nginx_rate_limit_block_is_present_but_commented() -> None:
    conf = _read("nginx.conf")
    rate_lines = [ln for ln in conf.splitlines() if "limit_req" in ln]
    assert rate_lines, "expected a commented rate-limit block"
    # Shipped off: every limit_req line must be commented out by default.
    assert all(ln.lstrip().startswith("#") for ln in rate_lines)


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
    assert "worker" in unit  # manage.py worker
    assert "User=deploy" in unit
    assert "WantedBy=multi-user.target" in unit


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
