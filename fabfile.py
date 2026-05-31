"""Fabric tasks: the deploy gate and everything that needs SSH.

Day-to-day local commands (dev, test, lint, fmt, typecheck, migrate,
migration, downgrade, setup, shell, worker, soniq-setup) live in the `pave`
console script - see app/cli.py. Fabric earns its keep when there are
Connections to manage and hosts to target, which is exactly what `deploy`
and the remote tasks below do.

`fab validate` stays here because it is the deploy gate: `fab deploy` will
not ship without it, so it sits next to the SSH code it gates. Its local
checks are delegated to the pave CLI rather than duplicated.
"""

import sys

import httpx
from fabric import Connection
from invoke import task

from app.settings import settings

# Deploy targets. `staging` / `production` mutate this in-process so a chained
# `fab production deploy` knows where to connect. Kept here, not in settings,
# because it is operator config, not application config.
_TARGETS = {
    "staging": {"host": "staging.usepave.dev", "domain": "staging.usepave.dev"},
    "production": {"host": "usepave.dev", "domain": "usepave.dev"},
}
_SELECTED: dict[str, str] = {}

DEPLOY_USER = "deploy"
APP_DIR = "/srv/pave"
RELEASES_DIR = f"{APP_DIR}/releases"
CURRENT = f"{APP_DIR}/current"
# Release-independent shared env file (see C1 / deploy/*.service). systemd
# loads it for the services; ad-hoc tasks must source it themselves.
SHARED_ENV = f"{APP_DIR}/shared/.env.production"

# How many release dirs to keep after a deploy. Each carries its own venv
# (100-300MB), so unbounded growth fills the disk. Keep enough that rollback
# always has a target.
KEEP_RELEASES = 5


def _target() -> dict[str, str]:
    if not _SELECTED:
        sys.exit("No environment selected. Use: fab production <task>")
    return _SELECTED


def _conn() -> Connection:
    t = _target()
    return Connection(host=t["host"], user=DEPLOY_USER)


def _with_env(command: str) -> str:
    """Wrap a remote command so it runs with .env.production loaded.

    systemd loads the env file for the services, but an ad-hoc Fabric task
    gets a bare login shell where DATABASE_URL is unset. Source the shared
    env file first so psql/pg_dump/restore see the connection string.
    """
    return f"set -a && . {SHARED_ENV} && set +a && {command}"


def _emit_deploy_event(release: str) -> None:
    """Best-effort deploy.success to Webhooq. httpx, not vrk: vrk grab is GET."""
    endpoint = settings.webhooq_endpoint
    if not endpoint:
        return
    try:
        httpx.post(
            endpoint,
            json={"event": "deploy.success", "release": release},
            timeout=5,
        )
    except Exception as exc:
        # Best-effort, so a failure never blocks the deploy, but it must be
        # visible: a silently-swallowed error hides a misconfigured endpoint.
        print(f"warning: deploy event POST to {endpoint} failed: {exc}")


# --- environment selectors ------------------------------------------------


@task
def staging(c):
    """Select the staging target for the tasks that follow."""
    _SELECTED.clear()
    _SELECTED.update(_TARGETS["staging"])


@task
def production(c):
    """Select the production target for the tasks that follow."""
    _SELECTED.clear()
    _SELECTED.update(_TARGETS["production"])


# --- the deploy gate ------------------------------------------------------


@task
def validate(c):
    """The deploy gate: css, migrations, tests, types must all pass.

    The gate composes the CSS build with the database migrations, tests,
    and typechecking. The local checks are delegated to the pave CLI
    (app/cli.py) rather than duplicated.
    """
    c.run(
        "bin/tailwindcss -i static/css/source.css -o static/css/app.css --minify",
        pty=True,
    )
    # Verify migrations against a throwaway db: the gate must never apply
    # migrations to the operator's real (configured) database.
    c.run("pave check-migrations", pty=True)
    c.run("pave test", pty=True)
    c.run("pave typecheck", pty=True)
    print("validate: all checks passed")


# --- remote tasks ---------------------------------------------------------


@task
def deploy(c):
    """Release-dir deploy: validate, ship, migrate, flip symlink, health check.

    On a failed post-flip health check the previous release is restored
    automatically (see rollback).
    """
    validate(c)

    # Preflight: the release is named after the HEAD commit, so refuse to ship
    # anything that would make that name lie. A dirty tree means the rsynced
    # working dir differs from the commit; an unpushed HEAD means shipping a
    # commit no teammate or CI has ever seen.
    if c.run("git status --porcelain", hide=True).stdout.strip():
        sys.exit("deploy aborted: working tree is dirty; commit or stash first")
    if not c.run(
        "git branch -r --contains HEAD", hide=True, warn=True
    ).stdout.strip():
        sys.exit("deploy aborted: HEAD is not on origin; push it first")

    t = _target()
    conn = _conn()
    release = c.run("vrk epoch --now", hide=True).stdout.strip()
    short_hash = c.run("git rev-parse --short HEAD", hide=True).stdout.strip()
    release_name = f"{release}-{short_hash}"
    release_path = f"{RELEASES_DIR}/{release_name}"

    conn.run(f"mkdir -p {release_path}")
    # Honour .gitignore so local .env secrets, the dev sqlite db, and tool
    # caches never ship; --delete keeps a reused release dir from carrying
    # stale files. The built static/css/app.css is tracked, so it still ships.
    c.run(
        f"rsync -az --filter=':- .gitignore' --exclude .git --delete ./ "
        f"{DEPLOY_USER}@{t['host']}:{release_path}/"
    )
    with conn.cd(release_path):
        conn.run("python -m venv .venv")
        conn.run(".venv/bin/pip install -q -r requirements.txt")
        conn.run(".venv/bin/alembic upgrade head")

    # Point this release's static/uploads at the persistent shared dir so
    # user uploads (avatars) survive the next deploy instead of being wiped
    # with the old release. .gitignore excludes static/uploads, so rsync never
    # ships a real directory here to collide with the symlink.
    conn.run(f"mkdir -p {APP_DIR}/shared/uploads")
    conn.run(f"ln -sfn {APP_DIR}/shared/uploads {release_path}/static/uploads")

    conn.run(f"ln -sfn {release_path} {CURRENT}")
    conn.run("sudo systemctl restart pave-api pave-worker")

    domain = t["domain"]
    health = c.run(
        f"vrk coax --times 5 --backoff exp:200ms -- "
        f"vrk grab https://{domain}/health | "
        f"vrk assert '.status == \"ok\"' "
        f"--message 'deploy failed health check'",
        warn=True,
    )
    if not health.ok:
        print("health check failed, rolling back")
        rollback(c)
        sys.exit(f"deploy aborted: {domain} did not become healthy")

    # The /health probe only covers the API. Confirm the worker is up too, so a
    # crash-on-start (bad job import, missing env) cannot ship as a green deploy
    # with a silently-dead job queue.
    worker = conn.run("systemctl is-active --quiet pave-worker", warn=True)
    if not worker.ok:
        print("worker is not active, rolling back")
        rollback(c)
        sys.exit("deploy aborted: pave-worker did not come up")

    # Prune old releases now the new one is live and healthy. Release names are
    # timestamp-prefixed, so a lexical sort is chronological; keep the newest
    # KEEP_RELEASES (the live one plus rollback targets) and delete the rest.
    conn.run(
        f"ls -1d {RELEASES_DIR}/*/ | sort | head -n -{KEEP_RELEASES} | "
        f"xargs -r rm -rf"
    )

    _emit_deploy_event(release_name)
    print(f"deployed {release_name} to {domain}")


@task
def rollback(c):
    """Point `current` back at the previous release and restart services."""
    conn = _conn()
    # Order by name, not mtime: release dirs are timestamp-prefixed, so a
    # reverse name sort is the stable chronological order (rsync and restores
    # rewrite mtimes, which would scramble `ls -t`). Second entry = previous.
    previous = conn.run(
        f"ls -1d {RELEASES_DIR}/*/ | sort -r | sed -n 2p", hide=True
    ).stdout.strip()
    if not previous:
        sys.exit("no previous release to roll back to")
    conn.run(f"ln -sfn {previous.rstrip('/')} {CURRENT}")
    conn.run("sudo systemctl restart pave-api pave-worker")
    print(f"rolled back to {previous}")


@task
def logs(c, service="pave-api", lines=100):
    """Tail journald logs for a service (pave-api or pave-worker)."""
    _conn().run(f"sudo journalctl -u {service} -n {lines} -f", pty=True)


@task
def ssh(c):
    """Open an interactive shell on the selected host."""
    _conn().run("$SHELL -l", pty=True)


@task
def psql(c):
    """Open psql against the production database on the host."""
    _conn().run(_with_env('psql "$DATABASE_URL"'), pty=True)


@task
def backup(c):
    """Dump the database and verify the dump's checksum with vrk digest."""
    conn = _conn()
    stamp = c.run("vrk epoch --now", hide=True).stdout.strip()
    path = f"{APP_DIR}/backups/db-{stamp}.sql.gz"
    conn.run(f"mkdir -p {APP_DIR}/backups")
    conn.run(_with_env(f'pg_dump "$DATABASE_URL" | gzip > {path}'))
    conn.run(f"vrk digest --algo sha256 --file {path} --compare")
    print(f"backup written and verified: {path}")


@task
def restore(c, path, yes=False):
    """Restore the database from a gzipped dump path on the host.

    Destructive, so it is guarded: pass --yes to confirm. A safety backup of
    the current database is taken first, and the restore runs in a single
    transaction so a corrupt dump rolls back cleanly instead of half-applying.
    """
    if not yes:
        sys.exit(
            "restore aborted: this overwrites the live database. "
            "Re-run with --yes to confirm."
        )
    conn = _conn()
    conn.run(f"vrk digest --algo sha256 --file {path} --compare")
    # Safety net: snapshot the current state before clobbering it.
    backup(c)
    conn.run(_with_env(f'gunzip -c {path} | psql --single-transaction "$DATABASE_URL"'))
    conn.run("sudo systemctl restart pave-api pave-worker")
    print(f"restored from {path}")


# --- one-time host hardening ----------------------------------------------
#
# Optional, idempotent, run once per host. Each is a thin sequence of sudo
# calls: nothing here is on the deploy path, so a server can be deployed to
# before any of these have run. DEPLOY.md says which to skip behind a cloud
# firewall or Cloudflare. setup-ssh is last on purpose: it can lock you out
# if key auth is not already working.


@task(name="setup-firewall")
def setup_firewall(c):
    """ufw: deny inbound by default, allow SSH + HTTP + HTTPS only."""
    conn = _conn()
    conn.run("sudo apt-get install -y ufw")
    conn.run("sudo ufw default deny incoming")
    conn.run("sudo ufw default allow outgoing")
    conn.run("sudo ufw allow OpenSSH")
    conn.run("sudo ufw allow 80/tcp")
    conn.run("sudo ufw allow 443/tcp")
    conn.run("sudo ufw --force enable")
    print("firewall: ufw enabled (SSH/80/443 only)")


@task(name="setup-fail2ban")
def setup_fail2ban(c):
    """Install fail2ban with the default sshd jail enabled."""
    conn = _conn()
    conn.run("sudo apt-get install -y fail2ban")
    conn.run("sudo systemctl enable --now fail2ban")
    print("fail2ban: installed, sshd jail active")


@task(name="setup-tls")
def setup_tls(c):
    """Obtain a Let's Encrypt certificate for the selected domain (Certbot)."""
    t = _target()
    conn = _conn()
    conn.run("sudo apt-get install -y certbot")
    conn.run("sudo mkdir -p /var/www/certbot")
    conn.run(
        f"sudo certbot certonly --webroot -w /var/www/certbot "
        f"-d {t['domain']} --non-interactive --agree-tos "
        f"-m admin@{t['domain']}"
    )
    conn.run("sudo systemctl reload nginx")
    print(f"tls: certificate issued for {t['domain']}")


@task(name="setup-backups")
def setup_backups(c):
    """Install backup.service + backup.timer from the release and enable it."""
    conn = _conn()
    src = f"{CURRENT}/deploy"
    for unit in ("backup.service", "backup.timer"):
        conn.run(f"sudo cp {src}/{unit} /etc/systemd/system/{unit}")
    conn.run(f"sudo chmod +x {CURRENT}/deploy/backup.sh")
    conn.run("sudo systemctl daemon-reload")
    conn.run("sudo systemctl enable --now backup.timer")
    print("backups: nightly timer enabled")


@task(name="setup-auto-updates")
def setup_auto_updates(c):
    """Enable unattended security upgrades."""
    conn = _conn()
    conn.run("sudo apt-get install -y unattended-upgrades")
    conn.run(
        "echo unattended-upgrades unattended-upgrades/enable_auto_updates "
        "boolean true | sudo debconf-set-selections"
    )
    conn.run(
        "sudo dpkg-reconfigure -f noninteractive unattended-upgrades"
    )
    print("auto-updates: unattended security upgrades enabled")


@task(name="setup-swap")
def setup_swap(c, size="2G"):
    """Create a swapfile if none exists (recommended under 4GB RAM)."""
    conn = _conn()
    has_swap = conn.run("swapon --show", hide=True, warn=True).stdout.strip()
    if has_swap:
        print("swap: already present, nothing to do")
        return
    conn.run(f"sudo fallocate -l {size} /swapfile")
    conn.run("sudo chmod 600 /swapfile")
    conn.run("sudo mkswap /swapfile")
    conn.run("sudo swapon /swapfile")
    conn.run(
        "grep -q '/swapfile' /etc/fstab || "
        "echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab"
    )
    print(f"swap: {size} swapfile active and persisted")


@task(name="setup-log-rotation")
def setup_log_rotation(c):
    """Cap journald disk use so logs cannot fill the disk."""
    conn = _conn()
    conn.run(
        "sudo sed -i 's/^#\\?SystemMaxUse=.*/SystemMaxUse=500M/' "
        "/etc/systemd/journald.conf"
    )
    conn.run("sudo systemctl restart systemd-journald")
    print("log-rotation: journald capped at 500M")


@task(name="setup-monitoring")
def setup_monitoring(c):
    """Print the health URL to register with an external uptime monitor.

    Uptime monitoring is external by design (it must run off-host to catch a
    fully-down server), so this task verifies the endpoint and tells you what
    to point UptimeRobot at rather than installing anything.
    """
    t = _target()
    url = f"https://{t['domain']}/health"
    c.run(
        f"vrk grab {url} | vrk assert '.status == \"ok\"' "
        f"--message 'health endpoint not reachable yet'",
        warn=True,
    )
    print(f"monitoring: register an UptimeRobot HTTP(s) monitor for {url}")


@task(name="setup-ssh")
def setup_ssh(c):
    """Harden sshd: disable password + root login. Run LAST, after key auth.

    This is deliberately the last hardening task. If key-based login is not
    already working, disabling password auth locks you out of the box.
    """
    conn = _conn()
    conn.run(
        "sudo sed -i 's/^#\\?PasswordAuthentication.*/"
        "PasswordAuthentication no/' /etc/ssh/sshd_config"
    )
    conn.run(
        "sudo sed -i 's/^#\\?PermitRootLogin.*/PermitRootLogin no/' "
        "/etc/ssh/sshd_config"
    )
    conn.run("sudo sshd -t")  # validate before reload, never reload a bad config
    conn.run("sudo systemctl reload ssh")
    print("ssh: password and root login disabled")
