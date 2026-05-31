# Deploy

The end-to-end deploy reference. For your first deploy, [Getting Started](getting-started.md) is the friendlier walkthrough. This page is what you come back to once Pave is running and you need to harden, scale, or debug.

## The deploy in one diagram

```mermaid
flowchart TD
    A[fab production deploy] --> B[fab validate locally]
    B -->|env, css, migrations, tests, types| C{ok?}
    C -- no --> X[abort, server untouched]
    C -- yes --> D[rsync to /srv/pave/releases/ID/]
    D --> E[build venv]
    E --> F[run migrations]
    F --> G[flip current symlink]
    G --> H[systemctl restart pave-api pave-worker]
    H --> I[probe /health with retries]
    I -- 200 ok --> J[done]
    I -- failed --> K[flip symlink back]
    K --> L[restart services on previous release]
    L --> M[exit non-zero]
```

Two important properties:

1. **Nothing touches the server until `fab validate` passes locally.** A broken commit cannot ship.
2. **The symlink flip is the only atomic moment.** Before it, the server is on the old release. After it, the new release is live. If the post-flip health check fails, the symlink flips back automatically and the previous release restarts.

---

## Fresh-server prep

Covered step by step in [Getting Started, Part 3](getting-started.md#part-3---prepare-a-vps). Checklist:

- [ ] `deploy` user with passwordless sudo for `systemctl`
- [ ] PostgreSQL installed, database and role created
- [ ] `nginx` installed, site configured
- [ ] `/srv/pave/` owned by `deploy`
- [ ] `.env.production` placed at `/srv/pave/shared/.env.production`
- [ ] systemd units installed and enabled (they will fail until first deploy lands)
- [ ] TLS via certbot

After this, every deploy is `fab production deploy`.

A `fab production setup-tls` task ships with the repo for one-shot host hardening (firewall, TLS bootstrap). Read it before running it on a host you have already configured manually.

---

## The pipeline, step by step

### 1. `fab validate` (local)

Runs in order: CSS build (`bin/tailwindcss`), migrations against a scratch DB, the full test suite, mypy. Stops at the first failure. The server is not contacted until validate succeeds.

### 2. Release stamping

`vrk epoch` produces an immutable release id like `20260527T140312Z`. The id names the directory, the journald log span, and the rollback target.

### 3. rsync

The project tree (minus `.git`, `.venv`, `__pycache__`, `node_modules`, and the test database) rsyncs to `/srv/pave/releases/{id}/`. The transfer is incremental; only changed files cross the wire after the first deploy.

### 4. Build the venv

A fresh `python -m venv` runs inside the release directory. `pip install -r requirements.txt` follows. Each release has its own venv, so pinning a new package version is atomic with the code that uses it.

### 5. Migrations

`alembic upgrade head` runs against the production database, against the *new* release's code. The old release is still serving traffic. Migrations must therefore be backward-compatible with the old code: add columns, do not drop or rename them in the same deploy.

### 6. Symlink flip

`/srv/pave/current` -> `/srv/pave/releases/{new-id}/`. This is a single `ln -sfn` call; readers of `current` either see the old target or the new one, never an empty pointer.

### 7. Restart services

`sudo systemctl restart pave-api pave-worker`. Gunicorn drops its workers (`SIGTERM`), waits for in-flight requests, and respawns reading the new code. Soniq picks up where it left off; in-flight jobs that crashed are retried.

### 8. Health probe

`vrk coax | vrk grab | vrk assert '.status == "ok"'` against `https://your-domain/health`, with retries and exponential backoff. The probe checks both HTTP 2xx and JSON shape. A 200 with `{"status":"degraded"}` is treated as failure.

### 9. On failure

The Fabric task flips the symlink back, restarts the services, and exits non-zero. Releases older than the last few are kept on disk; older directories are pruned.

---

## Hardening

The defaults in `deploy/nginx.conf` and the systemd units include HSTS, `X-Content-Type-Options`, modern TLS ciphers, and a request-size cap. The remaining work is at the OS level.

### UFW (firewall)

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### fail2ban

```bash
sudo apt-get install -y fail2ban
# /etc/fail2ban/jail.d/sshd.local
[sshd]
enabled = true
maxretry = 3
bantime = 1h
```

### Unattended upgrades

```bash
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

### journald caps

So a chatty deploy day does not eat your disk:

```ini
# /etc/systemd/journald.conf.d/limits.conf
[Journal]
SystemMaxUse=2G
SystemKeepFree=2G
SystemMaxFileSize=200M
```

`sudo systemctl restart systemd-journald` to apply.

### Disable root SSH

```bash
# /etc/ssh/sshd_config.d/no-root.conf
PermitRootLogin no
PasswordAuthentication no
```

`sudo systemctl restart sshd`. Confirm you can still log in as `deploy` *before* closing the second terminal.

---

## Multiple hosts

Pave starts on one host. Growing to more is a Fabric host-list change, not a redesign.

### Two app hosts, shared Postgres

```python
# fabfile.py
@task(hosts=["deploy@app1.example.com", "deploy@app2.example.com"])
def production(c): ...
```

`fab production deploy` rsyncs to both hosts in parallel and runs migrations once (Alembic detects the no-op on the second host). Put a load balancer in front (Nginx, Caddy, HAProxy, or your cloud's LB) pointed at both Gunicorn sockets over a private network.

### Separate worker host

Move `pave-worker.service` to a dedicated host. The worker only needs the same `.env.production` and a route to the database. A Fabric task can target a different host list for the worker role.

### Same Postgres, different roles

Postgres on its own box (managed or VM) is usually the first move. Set `DATABASE_URL` on each app/worker host to point at it. Nothing else changes.

---

## Backups

`deploy/backup.service`, `deploy/backup.timer`, and `deploy/backup.sh` ship with the repo. The script runs `pg_dump`, computes a sha256 digest, and writes a compressed dump under `/var/backups/pave/`. Install:

```bash
sudo cp deploy/backup.service deploy/backup.timer /etc/systemd/system/
sudo systemctl enable --now backup.timer
```

Defaults: daily, 14 days of dumps retained. Edit `deploy/backup.sh` to push to S3, B2, or a remote host.

`fab backup` runs an on-demand dump; `fab restore` is the inverse. Both call `vrk digest --algo sha256 --compare` so a silently corrupted dump fails fast.

> **Backups you have not restored are not backups.** Once a quarter, restore the latest dump into a scratch database and run the app against it. The first time you actually need a backup is the wrong time to discover that the dumps are empty.

---

## Rollback

Automatic, on health-check failure. Manual:

```bash
fab rollback
```

This flips `current` to the previous release and restarts the services. No database changes are undone; migrations need their own reversal if they shipped breaking changes, which is the reason migrations should be backward-compatible in the first place (see [migrations.md](migrations.md)).

---

## Troubleshooting

### `fab production deploy` hangs

Almost always SSH. Run `ssh deploy@your-server "echo ok"` directly and see whether it returns. If `sudo` prompts for a password, the sudoers rule for `deploy` is missing or wrong.

### "validate failed" before anything ships

Good. Read the output - it points at exactly one of: env schema, CSS build, migrations, tests, mypy. Fix locally, re-run.

### Deploy succeeded, site returns 502

Gunicorn is not listening on `/run/pave/pave.sock`. Check `journalctl -u pave-api -n 100`. Most common: a missing env var, or a syntax error in code that imports at startup.

### Deploy succeeded, site loads, but the new feature is missing

Browser cached. Hard reload. If still missing, you deployed from the wrong branch - check `git log -1` matches the release id stamped in the deploy output.

### `/health` returns 200 but the app is actually broken

The health endpoint is shallow on purpose. Deepen it in `app/routers/health.py` for the checks that matter to you (DB ping, queue depth, an external dependency). The deploy probe will pick up the new shape automatically.

### `fab logs` shows nothing

The service is not running, or you are targeting the wrong host. `fab ssh` to confirm, then `systemctl status pave-api pave-worker`.
