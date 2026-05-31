# Security policy

Thanks for taking the time to make Pave safer. This document covers how to report a vulnerability, what is in scope, the defaults Pave ships with, and the things only an operator can do for their own deployment.

Pave is a starter, not a managed platform. It ships sensible defaults and documents the rest. The line between "Pave's job" and "yours" is drawn explicitly below.

---

## Reporting a vulnerability

Email **security@usepave.dev** with details. PGP is not required.

Please do **not** open a public GitHub issue, draft pull request, or discussion for a suspected security bug. A public report gives anyone watching the repo a head start.

A useful report includes:

- A short description of the issue and the impact you think it has.
- The Pave commit or version you tested against (the `app_version` field on `/health`, or the release id from `fab production deploy` output).
- Steps to reproduce, ideally a minimal patch or curl invocation.
- Any logs, stack traces, or request ids (`X-Request-ID`) you have.

If you stumbled on the bug while testing a deployed Pave site you do not own, stop and contact that site's operator first. We cannot authorize testing against third-party deployments.

### What to expect back

| Step | Window |
|---|---|
| Acknowledgement that the report was received | 72 hours |
| Initial assessment (severity, reproducibility, plan) | 7 days |
| Fix or detailed status update, high severity | 14 days |
| Fix or detailed status update, medium severity | 30 days |
| Low severity | best effort, batched with the next release |

"High severity" means remote code execution, auth bypass, privilege escalation, secrets disclosure, or anything that compromises an entire deployment. "Medium" is anything that requires a specific configuration, partial information disclosure, CSRF gaps on a non-critical route, and similar. "Low" is hardening gaps and defence-in-depth findings that do not constitute a direct bug.

We do coordinated disclosure: we will agree on a public-disclosure date with you, ship the fix, then publish a short writeup. You get credit by name and link unless you ask for anonymity. If a CVE is appropriate, we request one through GitHub's advisory database.

---

## Supported versions

Pave is at `0.0.1`. It is pre-1.0 and the API may still shift.

| Version | Supported |
|---|---|
| `main` branch | yes |
| Tagged pre-1.0 releases | no, please track `main` |
| Once 1.0 ships | the latest minor will receive security fixes |

If you are running a fork or a long-lived branch off `main`, security fixes are still on you to rebase in. We will document the relevant commit hashes in the advisory so you can cherry-pick.

---

## Scope

### In scope

- Code under `app/`. Routes, jobs, auth helpers, middleware, services, settings.
- Default configuration in `deploy/` (the Nginx config, the systemd units, the backup script).
- The `fab` deploy pipeline in `fabfile.py` and the local checks it runs.
- The default content in `templates/` and `static/`, to the extent a default page can carry a vulnerability (XSS in a shipped template, an unsafe HTMX swap pattern, etc.).

### Out of scope

- **Operator misconfiguration.** Weak `SECRET_KEY`, world-readable `.env.production`, missing firewall, password SSH left on, an unprivileged service account that was granted full sudo, a database exposed to the public internet. Pave documents the right defaults in `docs/deploy.md` and `docs/config.md`; following them is the operator's job.
- **Upstream issues.** Bugs in FastAPI, Starlette, SQLAlchemy, Pydantic, PostgreSQL, bcrypt, Soniq, or any other dependency. Please report those to the project that owns the code. If Pave's usage pattern is what makes an upstream bug exploitable, that part is in scope.
- **Social engineering against project contributors.** Phishing the maintainer, typosquatted packages targeting Pave users, GitHub account takeovers, and similar.
- **Findings from automated scanners with no demonstrated impact.** "Tool X says this header is missing" without a working exploit is feedback, not a vulnerability report. We are happy to receive it, just not through the security inbox.
- **Self-XSS, clickjacking on routes that have no sensitive action, and other low-impact theoretical issues** without a concrete attacker scenario.

---

## Security defaults Pave ships with

These are wired the day you clone. You do not opt into them.

**Sessions and cookies** (`app/auth/sessions.py`, `app/auth/dependencies.py`):

- DB-backed sessions, not pure signed cookies. The cookie is an opaque 256-bit random token; only its sha256 hash is stored. A database dump cannot be replayed as a valid cookie.
- Cookie flags: `HttpOnly`, `SameSite=Lax`, and `Secure` whenever `DEBUG` is false.
- Per-device revocation, "sign out everywhere" on password reset, and an "active devices" list.
- 14-day session lifetime, last-used timestamp written at most once a minute per session.

**CSRF**: middleware-enforced token on every mutating route. See `docs/auth.md`.

**Passwords** (`app/auth/password.py`): bcrypt via the `bcrypt` package. Per-password salt, hash carries its own parameters, verification is constant-time. OAuth-only accounts have no `password_hash` and cannot be brute-forced.

**Rate limiting**: signup, login, forgot, and reset are rate-limited per IP. Password-reset responses are uniform (always 200) so an attacker cannot enumerate registered emails.

**Transport and HTTP headers** (`deploy/nginx.conf`):

- HSTS on by default in production.
- `X-Content-Type-Options: nosniff`.
- Modern TLS ciphers, TLS 1.2+ only.
- Strict referrer policy.
- A configured request-size cap.

**Host allow-list** (`app/settings.py`): `ALLOWED_HOSTS` is enforced. The default of `*` is for local dev; production must set a comma list (the app will fail to start otherwise).

**Secret handling** (`docs/config.md`):

- `.env.production` lives on the server as `chmod 600`, owned by the `deploy` user.
- The file is not in git, not in the release directory, and a fresh deploy does not touch it.
- systemd loads it via `EnvironmentFile=`, not the app, so a missing file is a startup failure rather than a runtime one.

**Hardening recommendations** (`docs/deploy.md`): UFW, fail2ban for sshd, unattended-upgrades, journald caps, disabling root SSH and password auth. These are documented as default-on operator steps.

---

## Crypto choices

| Purpose | Primitive | Notes |
|---|---|---|
| Password hashing | bcrypt | `app/auth/password.py`. Per-password salt generated by `bcrypt.gensalt()`. Cost factor is the library default. |
| Session token | `secrets.token_urlsafe(32)` | 256 bits of entropy, opaque to the server. |
| Session token storage | sha256 of the token | Only the hash lands in the `sessions` table. |
| Cookie integrity | not signed | The cookie value is the lookup key; integrity comes from the DB row, not a signature. |
| Verification and reset tokens | `secrets.token_urlsafe` plus a stored fingerprint | One-hour expiry on reset links. See `app/auth/tokens.py`. |
| `SECRET_KEY` | random 48+ bytes | Signs the in-app tokens documented in `docs/config.md`. |

Rotating `SECRET_KEY` invalidates every signed token Pave has issued. It is the correct lever for "an employee left and might still have a token", but it logs everyone out. See the "Secrets" section of `docs/config.md` for the rotation procedure.

---

## What's on the operator

Things Pave cannot do for you. Each of these is a routine operations task, not a one-time setup:

- Rotate `SECRET_KEY` when an employee with server access leaves, and revoke their SSH key from `~deploy/.ssh/authorized_keys`.
- Restrict the `deploy` user's passwordless sudo to `systemctl` (and the specific units) only. A wide-open `NOPASSWD: ALL` defeats the purpose of having a non-root deploy user.
- Use key-only SSH. Set `PasswordAuthentication no` and `PermitRootLogin no` in `sshd_config.d/`.
- Apply security updates. `unattended-upgrades` covers most of it; kernel updates still need a reboot.
- Take backups *and* restore them. `fab backup` and `fab restore` ship with the repo; an untested backup is not a backup. Restore into a scratch database at least quarterly.
- Watch logs. `journalctl -u pave-api` and `journalctl -u pave-worker` are the source of truth. Set up Sentry (`SENTRY_DSN`) for grouped error tracking, and an external uptime monitor against `/health` (see `docs/monitoring.md`).
- Apply TLS at the database layer if Postgres is on a different host than the app. The shipped `DATABASE_URL` does not enforce `sslmode=require` because the default is "Postgres on the same box". Set it explicitly when the topology changes.
- Vet and update dependencies. `pip list --outdated`, `pip-audit`, and your favourite SCA tool are not part of `fab validate`. Add them to a scheduled job if you care about CVE response time on third-party packages.

---

## Known limitations

Pave is a starter, not a turnkey compliance platform. By default it does not include:

- A web application firewall. Run behind Cloudflare, AWS WAF, or your cloud's equivalent if you need one.
- DDoS protection. Nginx and fail2ban handle the obvious cases. Volumetric attacks need an upstream provider.
- A compliance posture for SOC 2, HIPAA, PCI, ISO 27001, or similar. There is no audit-log table by default, no enforced password-rotation policy, no SCIM. These are scope choices, not oversights.
- Per-tenant data isolation beyond what `user_id` columns give you. Multi-tenant apps with hard isolation needs require additional work.
- API tokens or service accounts. Sessions are interactive only. Programmatic access is a feature you build, with `app/auth/sessions.py` as a sibling pattern.
- Egress filtering. Outbound HTTP from the app (email provider, Sentry, OAuth) is allowed without restriction.
- Encryption at rest beyond what Postgres and the disk layer provide.

If any of these are dealbreakers, Pave is probably not the right starting point. The `docs/why-pave.md` page covers the explicit non-goals.

---

## Hardening checklist

The OS-level hardening Pave recommends, in link form. Each is detailed in `docs/deploy.md`:

- [ ] UFW configured, only 22/80/443 open inbound.
- [ ] fail2ban installed with the sshd jail enabled.
- [ ] unattended-upgrades enabled with `dpkg-reconfigure -plow`.
- [ ] Root SSH disabled (`PermitRootLogin no`).
- [ ] Password SSH disabled (`PasswordAuthentication no`).
- [ ] journald caps set so a chatty deploy day does not fill the disk.
- [ ] `.env.production` owned by `deploy`, mode `600`.
- [ ] `deploy` user's sudoers entry restricted to the systemd units it operates.
- [ ] Backups running on the timer, with a restore tested in the last quarter.
- [ ] External uptime monitor pointed at `/health` with a keyword check on `"status":"ok"`.
- [ ] `SENTRY_DSN` set, with a deliberate test exception confirmed.
- [ ] `ALLOWED_HOSTS` set to your real hostnames, not `*`.
- [ ] TLS certificate auto-renewal verified (certbot timer or equivalent).

A passing checklist is the minimum, not the ceiling. Threat-model your own app on top.

---

## Thanks

Researchers who report responsibly are credited in the advisory and in the release notes for the fix. If you would like a public thank-you outside that, let us know in the report and we'll add it to a `SECURITY-THANKS` section once we have one to populate.
