# Getting Started

This page takes you from a fresh clone to a live, TLS-terminated app on a server you own. Plan on 15 minutes if you have a VPS and a domain ready, or 5 minutes if you only want to run it locally first.

## What you will have in 15 minutes

- Pave running on your laptop at `http://127.0.0.1:8000`
- One edit you made yourself, visible in the browser
- The same app running at `https://your-domain.com` on a real server
- A `/health` endpoint your monitoring can probe
- A working rollback path if the next deploy goes wrong

## Prerequisites

**Local machine:**

- Python 3.12 or newer
- `git`
- An SSH key (`~/.ssh/id_ed25519` or similar). If you do not have one: `ssh-keygen -t ed25519`.

**Server (only needed for Part 3 onward):**

- A fresh Ubuntu 22.04+ or Debian 12+ VPS with a public IP. Any provider works (Hetzner, DigitalOcean, Linode, OVH, EC2).
- A domain or subdomain with an A record pointing at that IP. DNS must resolve before the TLS step.
- Root SSH access for the one-time prep.

You do not need Docker, Node.js, or a paid platform account anywhere.

---

## Part 1 - Run Pave locally

### Clone and install

```bash
git clone https://github.com/abhinavs/pave && cd pave
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pip install -e .
```

The last command installs the project itself, which gives you the `pave` console script.

### Configure

```bash
cp .env.example .env
```

By default `.env` points at PostgreSQL. If you do not have Postgres installed locally, open `.env` and set:

```bash
USE_SQLITE=true
```

That switches the app to a SQLite file under `./var/`. Everything still works: auth, sessions, migrations, the job queue.

### Bootstrap and run

```bash
pave setup
pave dev
```

`pave setup` creates the database, runs migrations, and installs the Soniq job tables. It is safe to run more than once.

`pave dev` starts two processes together: the FastAPI server on port 8000 and the Tailwind watcher that rebuilds CSS on save.

**You should see:**

```
17:21:03 web.1  | INFO:     Uvicorn running on http://127.0.0.1:8000
17:21:03 css.1  | Rebuilding...
17:21:03 css.1  | Done in 142ms.
```

Open http://127.0.0.1:8000. The home page loads. Click around: `/blog`, `/about`, `/auth/login`. Visit `/webhooks` - that page is the reference for every UI component shipped with Pave.

**Common mistake:** if you started a separate `uvicorn` by hand, the Tailwind watcher will not be running and CSS changes will not appear. Always start with `pave dev`.

---

## Part 2 - Make your first change

You want proof you can edit this codebase. The fastest visible change is editing a markdown page.

Open `content/pages/about.md`. The top of the file looks like this:

```markdown
---
title: About Pave
description: What Pave is and why it exists.
published: true
---

Pave is a production starting point for full-stack Python web apps...
```

Change the first paragraph to whatever you like, save, and reload http://127.0.0.1:8000/about. Your edit is live.

**Why this works.** Pave's content system reads markdown files from `content/` at request time. No database table, no admin form, no rebuild. The same pattern works for blog posts under `content/blog/`.

**Next thing most people want:** add a route. [docs/your-first-feature.md](your-first-feature.md) walks one through end to end.

---

## Part 3 - Prepare a VPS

This is the longest step the first time you do it. Subsequent deploys to the same server are one command.

If you already have a server you have used before, skip to Part 4.

### Create a `deploy` user

SSH in as root and run:

```bash
adduser --disabled-password --gecos "" deploy
usermod -aG sudo deploy
mkdir -p /home/deploy/.ssh
cp /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh && chmod 600 /home/deploy/.ssh/authorized_keys
echo 'deploy ALL=(ALL) NOPASSWD: /bin/systemctl' > /etc/sudoers.d/deploy
```

Verify from your laptop:

```bash
ssh deploy@your-server "whoami && sudo systemctl status"
```

Should print `deploy` and a systemd status output with no password prompt.

### Install the system packages

Still as root (or via `sudo`):

```bash
apt-get update
apt-get install -y postgresql nginx python3.12 python3.12-venv rsync
```

### Create the database

```bash
sudo -u postgres createuser --pwprompt pave
sudo -u postgres createdb --owner pave pave_production
```

Remember the password. You will paste it into `DATABASE_URL` in a moment.

### Create the release directory

```bash
mkdir -p /srv/pave/releases
chown -R deploy:deploy /srv/pave
```

### Place `.env.production`

As `deploy`:

```bash
ssh deploy@your-server
nano /srv/pave/.env.production
```

Minimum contents:

```bash
DATABASE_URL=postgresql://pave:THE-PASSWORD@localhost/pave_production
SONIQ_DATABASE_URL=postgresql://pave:THE-PASSWORD@localhost/pave_production
SECRET_KEY=PASTE-THE-OUTPUT-OF-THE-COMMAND-BELOW
ALLOWED_HOSTS=your-domain.com,www.your-domain.com
DEBUG=false
LOG_LEVEL=info
```

Generate `SECRET_KEY` on your laptop:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### Install the systemd units and Nginx site

From your laptop, in the repo:

```bash
scp deploy/pave-api.service deploy/pave-worker.service deploy@your-server:/tmp/
scp deploy/nginx.conf deploy@your-server:/tmp/
```

On the server (as `deploy`, with `sudo`):

```bash
sudo mv /tmp/pave-api.service /tmp/pave-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pave-api pave-worker

# Nginx
sudo mv /tmp/nginx.conf /etc/nginx/sites-available/pave
sudo sed -i 's/{{domain}}/your-domain.com/g' /etc/nginx/sites-available/pave
sudo ln -s /etc/nginx/sites-available/pave /etc/nginx/sites-enabled/pave
sudo nginx -t && sudo systemctl reload nginx
```

The services will fail to start until the first deploy lands code in `/srv/pave/current/`. That is expected. Do not start them yet.

### TLS

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com -d www.your-domain.com
```

Certbot edits the Nginx site to add port 443 and a redirect. The renewal timer is installed automatically.

> **DNS check.** Before running certbot, confirm the A record has propagated: `dig +short your-domain.com` should return your server's IP. Certbot fails fast if it cannot resolve.

---

## Part 4 - Your first deploy

Back on your laptop, in the repo:

```bash
pip install fabric
```

Open `fabfile.py` and find the `production` host definition. Set it to your server:

```python
@task(hosts=["deploy@your-server.com"])
def production(c): ...
```

Then deploy:

```bash
fab production deploy
```

**What happens, in order:**

1. `fab validate` runs locally: env schema check, CSS build, migrations, tests, type check. If any step fails, nothing touches the server.
2. A release id is stamped (`vrk epoch`) and the tree is rsynced to `/srv/pave/releases/{id}/` on the server.
3. A fresh virtualenv is built in the new release directory and dependencies are installed.
4. Migrations run on the server against the production database.
5. The `/srv/pave/current` symlink atomically flips to the new release.
6. `systemctl restart pave-api pave-worker` picks up the new code.
7. `/health` is probed with retries. On success, the deploy is done. On failure, the symlink flips back and the services restart on the previous release before the command exits.

**You should see** (timing varies):

```
==> validate
    env schema ........ ok
    css build ......... ok
    migrations ........ ok
    tests ............. ok (124 passed in 8.31s)
    typecheck ......... ok
==> release 20260527T140312Z
    rsync ............. 0.4 MB
    venv .............. ok
    migrations ........ ok
    symlink flipped ... ok
    services restarted
==> health
    GET https://your-domain.com/health
    200 OK in 412ms - {"status":"ok"}
Deploy succeeded.
```

Open https://your-domain.com. The app is live.

---

## Verify and watch logs

From your laptop:

```bash
fab logs        # tail journald for pave-api and pave-worker
```

Or on the server:

```bash
journalctl -u pave-api -f
journalctl -u pave-worker -f
```

A green deploy plus a 200 from `/health` is the production smoke test. Add `/health` to whatever uptime monitor you use (UptimeRobot, Better Stack, or the `health-probe.yml` workflow that ships with this repo).

---

## Common mistakes

**The deploy fails at the health-check step and rolls back.**
The previous release is running again. Run `fab logs` to see why the new release returned non-200. Most common cause: a missing env var. Add it to `.env.production` on the server and try again.

**`fab production deploy` fails locally with "validate failed".**
Good. That is the gate doing its job. The error is from `pave test`, `pave lint`, `pave typecheck`, or env schema validation. Fix locally, then re-run.

**`systemctl status pave-api` shows "Active: failed".**
Three usual suspects: `.env.production` is missing or unreadable; `DATABASE_URL` points at a database that does not exist; the `deploy` user does not own `/srv/pave/`. Check `journalctl -u pave-api -n 50` for the exact line.

**The site loads but every page is 502 from Nginx.**
Gunicorn is not listening on `/run/pave/pave.sock`. `systemctl restart pave-api` and check `journalctl -u pave-api`.

**The site loads but CSS is missing.**
You deployed before running `fab validate` ever locally, so `static/css/app.css` was not built. Run `pave dev` once to rebuild it (or `bin/tailwindcss -i static/css/source.css -o static/css/app.css`) and redeploy.

---

## What to read next

You now have a working dev loop and a working deploy. Pick the next page based on what you want to build.

- Add your first feature (model + migration + route + template) -> [your-first-feature.md](your-first-feature.md)
- Building UI with the HTMX kit -> [components.md](components.md)
- Background jobs and the Soniq worker -> [background-jobs.md](background-jobs.md)
- Hardening the server (firewall, fail2ban, backups, journald caps) -> [deploy.md](deploy.md)
- Conventions for AI-assisted edits in this repo -> [../AGENTS.md](../AGENTS.md)
