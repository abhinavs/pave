"""Fabric tasks: the deploy gate and everything that needs SSH.

Day-to-day local commands (dev, test, lint, fmt, typecheck, migrate,
migration, downgrade, setup, console, worker, soniq-setup) live in the `pave`
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

# Deploy targets. `branch` is the ref the server checks out: each release is a
# snapshot of origin/<branch>. Add or edit environments here.
_TARGETS = {
    "staging": {
        "host": "staging.usepave.dev",
        "domain": "staging.usepave.dev",
        "branch": "main",
    },
    "production": {
        "host": "usepave.dev",
        "domain": "usepave.dev",
        "branch": "main",
    },
}
# The environment a bare `fab deploy` (or any task) targets when none is named.
# Defaults to staging so the dangerous target (production) always has to be
# typed in full: `fab production deploy`.
DEFAULT_ENV = "staging"
_SELECTED: dict[str, str] = {}

DEPLOY_USER = "deploy"
APP_DIR = "/srv/pave"
RELEASES_DIR = f"{APP_DIR}/releases"
CURRENT = f"{APP_DIR}/current"
# Repo the server clones and cuts release snapshots from. The deploy user needs
# read access to it (a deploy key in ~deploy/.ssh). Set this to your repo URL.
GIT_REPO = "git@github.com:usepave/pave.git"
REPO_DIR = f"{APP_DIR}/repo"
# Shared env file, loaded by the systemd units. Ad-hoc tasks source it directly.
SHARED_ENV = f"{APP_DIR}/shared/.env.production"
# One venv, shared across releases and updated in place each deploy (fast). A
# removed dependency lingers until `fab <env> rebuild-venv`, and rollback does
# not restore the previous dependency set. The systemd units run from here.
SHARED_VENV = f"{APP_DIR}/shared/venv"
# Pinned Tailwind binary, downloaded once. The CSS is built on the server during
# deploy, so the box needs its own copy. Keep the version in step with bin/.
SHARED_BIN = f"{APP_DIR}/shared/bin"
TAILWIND_VERSION = "v3.4.17"
TAILWIND_URL = (
    "https://github.com/tailwindlabs/tailwindcss/releases/download/"
    f"{TAILWIND_VERSION}/tailwindcss-linux-x64"
)

# Release dirs to keep after a deploy. Enough that rollback has a target,
# bounded so the disk does not fill.
KEEP_RELEASES = 5


def _target() -> dict[str, str]:
    if not _SELECTED:
        _SELECTED.update(_TARGETS[DEFAULT_ENV])
        print(f"no environment selected, using default: {DEFAULT_ENV}")
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
    """Best-effort deploy.success notification to the configured endpoint."""
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


def _ensure_repo(conn: Connection) -> None:
    """Clone the repo on first run, fetch on every run. Idempotent."""
    conn.run(f"test -d {REPO_DIR}/.git || git clone {GIT_REPO} {REPO_DIR}")
    conn.run(f"git -C {REPO_DIR} fetch --prune origin")


def _ensure_tailwind(conn: Connection) -> None:
    """Download the pinned Tailwind binary if it is missing. Reused across deploys."""
    conn.run(f"mkdir -p {SHARED_BIN}")
    conn.run(
        f"test -x {SHARED_BIN}/tailwindcss || "
        f"(curl -fsSL -o {SHARED_BIN}/tailwindcss {TAILWIND_URL} && "
        f"chmod +x {SHARED_BIN}/tailwindcss)"
    )


def _ensure_venv(conn: Connection) -> None:
    """Create the shared venv if it does not exist yet."""
    conn.run(f"test -d {SHARED_VENV} || python3 -m venv {SHARED_VENV}")


def _restart_services(conn: Connection) -> None:
    """Restart the API and worker on the current release.

    `restart` re-resolves the `current` symlink, so the new code loads. SIGTERM
    is graceful for both: gunicorn drains in-flight requests and the worker
    finishes its current job before exiting (bounded by TimeoutStopSec in the
    units), so a deploy never severs a live request or job mid-flight.
    """
    conn.run("sudo systemctl restart pave-api pave-worker")


@task
def deploy(c):
    """Validate, snapshot origin/<branch>, build, migrate, flip symlink, health check.

    The snapshot is cut from origin/<branch> on the server, the CSS is built
    there, and the shared venv is updated in place. On a failed post-flip health
    check the previous release is restored automatically (see rollback).
    """
    validate(c)

    t = _target()
    branch = t["branch"]
    # The server ships origin/<branch>, so local HEAD must equal that branch tip
    # and the tree must be clean, or it would deploy something other than what
    # validate just tested. Fetch first so the comparison is against the remote.
    c.run("git fetch origin", hide=True)
    if c.run("git status --porcelain", hide=True).stdout.strip():
        sys.exit("deploy aborted: working tree is dirty; commit or stash first")
    local_head = c.run("git rev-parse HEAD", hide=True).stdout.strip()
    remote_head = c.run(
        f"git rev-parse origin/{branch}", hide=True, warn=True
    ).stdout.strip()
    if local_head != remote_head:
        sys.exit(
            f"deploy aborted: HEAD is not the tip of origin/{branch}; "
            f"push it (or switch branch) so the server ships what you tested"
        )

    conn = _conn()
    _ensure_repo(conn)
    _ensure_tailwind(conn)
    _ensure_venv(conn)

    release = c.run("vrk epoch --now", hide=True).stdout.strip()
    short_hash = conn.run(
        f"git -C {REPO_DIR} rev-parse --short origin/{branch}", hide=True
    ).stdout.strip()
    release_name = f"{release}-{short_hash}"
    release_path = f"{RELEASES_DIR}/{release_name}"

    # `git archive` exports only tracked files and never the .git dir, so
    # gitignored secrets, the dev db, and caches cannot ride along.
    conn.run(f"mkdir -p {release_path}")
    conn.run(f"git -C {REPO_DIR} archive origin/{branch} | tar -x -C {release_path}")

    # app.css is gitignored, so the snapshot has none: build it here.
    conn.run(
        f"{SHARED_BIN}/tailwindcss "
        f"-i {release_path}/static/css/source.css "
        f"-o {release_path}/static/css/app.css --minify"
    )

    # Update the shared venv, then migrate against the new code while the old
    # release still serves traffic.
    conn.run(f"{SHARED_VENV}/bin/pip install -q -r {release_path}/requirements.txt")
    with conn.cd(release_path):
        conn.run(f"{SHARED_VENV}/bin/alembic upgrade head")

    # Persist user uploads across deploys: point the release at the shared dir.
    conn.run(f"mkdir -p {APP_DIR}/shared/uploads")
    conn.run(f"ln -sfn {APP_DIR}/shared/uploads {release_path}/static/uploads")

    conn.run(f"ln -sfn {release_path} {CURRENT}")
    _restart_services(conn)

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

    # /health only covers the API, so confirm the worker came up too: a
    # crash-on-start must not ship green with a silently-dead job queue.
    worker = conn.run("systemctl is-active --quiet pave-worker", warn=True)
    if not worker.ok:
        print("worker is not active, rolling back")
        rollback(c)
        sys.exit("deploy aborted: pave-worker did not come up")

    # Prune to the newest KEEP_RELEASES. Names are timestamp-prefixed, so a
    # lexical sort is chronological.
    conn.run(
        f"ls -1d {RELEASES_DIR}/*/ | sort | head -n -{KEEP_RELEASES} | xargs -r rm -rf"
    )

    _emit_deploy_event(release_name)
    print(f"deployed {release_name} to {domain}")


@task
def rollback(c):
    """Point `current` back at the previous release and restart services."""
    conn = _conn()
    # Order by name, not mtime: release names are timestamp-prefixed, so a
    # reverse name sort is the stable chronological order (mtimes get rewritten
    # by restores). Second entry = the previous release.
    previous = conn.run(
        f"ls -1d {RELEASES_DIR}/*/ | sort -r | sed -n 2p", hide=True
    ).stdout.strip()
    if not previous:
        sys.exit("no previous release to roll back to")
    conn.run(f"ln -sfn {previous.rstrip('/')} {CURRENT}")
    _restart_services(conn)
    print(f"rolled back to {previous}")


@task(name="rebuild-venv")
def rebuild_venv(c):
    """Recreate the shared venv from scratch and reinstall the live release.

    Deploys reuse one shared venv, so a removed or downgraded dependency leaves
    its old packages behind. This blows the venv away and rebuilds it from the
    current release's requirements, then restarts the services. Run it after a
    deploy that dropped a dependency, or after a Python upgrade on the host.
    """
    conn = _conn()
    conn.run(f"rm -rf {SHARED_VENV}")
    conn.run(f"python3 -m venv {SHARED_VENV}")
    conn.run(f"{SHARED_VENV}/bin/pip install -q -r {CURRENT}/requirements.txt")
    _restart_services(conn)
    print("rebuild-venv: shared venv recreated, services restarted")


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
    _restart_services(conn)
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
    conn.run("sudo dpkg-reconfigure -f noninteractive unattended-upgrades")
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
    """Cap journald disk use via a drop-in so logs cannot fill the disk.

    The app logs to stdout, which systemd captures into journald, so log
    retention is a journald setting, not the app's job. This installs
    deploy/journald.conf as a drop-in (override the shipped limits by editing
    that file and re-running). Requires a release to be live for {CURRENT}.
    """
    conn = _conn()
    conn.run("sudo mkdir -p /etc/systemd/journald.conf.d")
    conn.run(
        f"sudo cp {CURRENT}/deploy/journald.conf /etc/systemd/journald.conf.d/pave.conf"
    )
    conn.run("sudo systemctl restart systemd-journald")
    print("log-rotation: journald limits installed from deploy/journald.conf")


@task(name="setup-server")
def setup_server(c):
    """Bootstrap a fresh host: clone the repo, fetch Tailwind, build the venv.

    Idempotent, and `deploy` does all three on demand anyway, so this is just a
    convenience for prepping a box before the first deploy. It does not need a
    release to exist yet (unlike the other setup-* tasks).
    """
    conn = _conn()
    conn.run(f"mkdir -p {RELEASES_DIR} {APP_DIR}/shared")
    _ensure_repo(conn)
    _ensure_tailwind(conn)
    _ensure_venv(conn)
    print("setup-server: repo cloned, Tailwind fetched, shared venv ready")


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
