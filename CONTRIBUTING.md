# Contributing to Pave

Thanks for thinking about helping out. Pave is small enough that one good PR moves the needle.

Pave is at version `0.0.1`. It is pre-1.0, so the API may still shift and breaking changes are possible between releases. That is also why now is a good time to contribute: the rough edges are still being filed down, and your feedback shapes the 1.0.

---

## Quick setup

You need Python 3.12+, `git`, and either Postgres or `USE_SQLITE=true` in `.env`.

```bash
git clone https://github.com/abhinavs/pave && cd pave
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt && pip install -e .
cp .env.example .env && pave setup && pave dev
```

Open http://127.0.0.1:8000. The full walkthrough, including a VPS deploy, is in [docs/getting-started.md](docs/getting-started.md).

`pave setup` is idempotent. It creates the database (or skips if it already exists), runs migrations, and installs the Soniq queue tables. `pave dev` runs uvicorn and the Tailwind watcher together via honcho. If you start uvicorn by hand, CSS changes will not rebuild and you will spend half an hour wondering why your styles look stale.

If anything fails before `pave dev` prints `Uvicorn running on ...`, that is a setup bug and worth a report on its own. See [Reporting bugs](#reporting-bugs).

---

## Where to start

If you are looking for a first PR, any of these are useful and small enough to land in an afternoon.

| Kind of contribution | Where to look |
| --- | --- |
| Typo or wording fix in docs | `README.md`, `docs/*.md`, and the in-app markdown under `content/` |
| Doc improvement (a missing step, an unclear example) | Same files. Lead with what tripped you up. |
| New HTMX component | `templates/_components/`. See [docs/components.md](docs/components.md) and the webhook demo at `/webhooks` for the reference shape. |
| New OAuth provider | `app/auth/`. Google and GitHub are the references. Same shape, different endpoints and a different `provider` string. |
| Bug fix | GitHub Issues, filtered by `bug`. Reproduce locally first. |

A few notes that save back-and-forth on review:

- **Docs PRs are PRs too.** A clear correction to `docs/getting-started.md` is worth as much as a code change. Do not apologize for "just a docs fix".
- **New components belong in `templates/_components/` and need a reference render** on `/webhooks` (or wherever similar components are demoed). If reviewers cannot see the component running, the PR is harder to land.
- **New OAuth providers** should follow the existing `app/auth/oauth_*.py` pattern (callback URL, token exchange, profile fetch, account linking). The settings keys go through the three-place rule below.

If you want to work on something larger, please open a discussion before writing the code. See [Suggesting changes to architecture](#suggesting-changes-to-architecture).

---

## The three-place rule for env vars

Every setting lives in three files. Forget one and the next contributor's clone will break on startup with a message about a missing variable.

| File | What it holds |
| --- | --- |
| `.env.example` | The variable name, an example value, and a one-line comment explaining what it is |
| `.env.schema` | Declares variables as required or optional:default |
| `app/settings.py` | A typed field on the `Settings` class so the app reads it |

This is also covered in [AGENTS.md](AGENTS.md), under "Environment variables". If you ever feel like skipping one of the three, read that section first.

---

## Code style

Two formatters, one type checker, one test runner. Run them in this order before you push.

```bash
pave fmt          # ruff format (rewrites files in place)
pave lint         # ruff check (lints, including import order)
pave typecheck    # mypy app/ in strict mode
pave test         # pytest, in-memory SQLite, fast
```

Conventions worth knowing up front:

- **No em-dashes anywhere.** Use a comma, a colon, or two sentences instead. This applies to code comments, docstrings, markdown, and commit messages.
- **Sentence-case comments and docstrings.** "Fetch the user's sessions", not "Fetch The User's Sessions".
- **mypy strict on `app/`.** All public functions need type annotations.
- **Imports in three groups:** stdlib, third-party, local (`from app.`) last. Ruff enforces it; `pave fmt` sorts them for you.
- **One blank line between logical blocks inside a function.** Two blank lines between top-level defs.

If `pave fmt` reformats your code, commit the reformatted version. Do not argue with ruff. If `pave typecheck` fails on a third-party stub, add a small typed shim in `app/` rather than scattering `# type: ignore` at call sites.

A few words to keep out of code, comments, docs, and commit messages: "robust", "seamless", "blazing-fast", "world-class". They mean nothing concrete and they make the docs sound like marketing copy. Describe what the thing does instead.

---

## Branching and PR flow

Work on a branch named for the change: `fix-session-expiry`, `add-discord-oauth`, `docs-getting-started-typos`. One concern per PR.

A good PR:

- Does one thing. If you find yourself writing "and" in the title, it is probably two PRs.
- Includes a test for any new behavior or fixed bug. New routes need at least a happy-path test plus the failure mode callers depend on (validation rejection, auth gate, idempotency, not-found). See [docs/testing.md](docs/testing.md) for fixtures and patterns.
- Updates the docs that describe what you changed. If you added a setting, it appears in `docs/config.md`. If you added a command, it appears in [AGENTS.md](AGENTS.md) and `README.md` where the others are listed.
- Passes `fab validate` locally before you click "Ready for review".

`fab validate` is the same gate that `fab deploy` runs. It builds CSS, applies migrations to a throwaway DB, runs the full test suite, and runs mypy. If `fab validate` is green, your PR will pass CI.

```bash
fab validate
```

If it fails, fix it locally. Pushing a red PR and hoping CI is more forgiving wastes everyone's time, including the CI minutes.

---

## Commit messages

Imperative mood. Write the message as if it is finishing the sentence "This commit will...".

| Good | Bad |
| --- | --- |
| `add discord oauth provider` | `added discord oauth provider` |
| `fix session expiry off-by-one` | `fixes session expiry off-by-one` |
| `update getting-started for sqlite path` | `updating docs` |

The subject line should fit in about 70 characters. There is no hard rule on the body: skip it when the subject says everything, write a paragraph when context matters (why now, why this approach, what you ruled out).

One change per commit when you can manage it. A clean history makes `git bisect` actually work the day you need it.

If you end up with a messy local history (three commits of "wip", a fourth that fixes the test), squash before opening the PR. `git rebase main` and `git commit --fixup` are your friends. The reviewer should see the change you intended to make, not the journey you took to get there.

---

## Migrations

Migrations run automatically during `fab deploy`, on the server, before the symlink flips. You should never SSH in and run `alembic upgrade head` by hand.

The local workflow for a schema change:

```bash
# 1. Edit or add the model under app/models/, then register it in app/models/__init__.py.
pave migration --message "add snippets table"

# 2. Open the generated file in alembic/versions/. Read upgrade() and downgrade().
#    Autogenerate is a draft. It misses column type changes, check constraints,
#    server defaults, and JSON columns on SQLite.

# 3. Apply.
pave migrate

# 4. Test the downgrade. Non-optional.
pave downgrade
pave migrate
```

If `pave downgrade` errors or leaves the schema in a weird state, fix the `downgrade()` function before committing. A migration without a working downgrade is a half-written migration.

The full set of rules, including the three-deploy pattern for renames and drops, is in [docs/migrations.md](docs/migrations.md). The short version: migrations must be backward-compatible with the previous release, because the old workers keep serving traffic for a few seconds after the migration runs and before the new release is live.

If you are dropping or renaming a column, split the change across three deploys: add the new column and backfill, then switch the code to read and write it, then drop the old column. Each step is independently reversible. Trying to do all three in one PR is the most common way a Pave deploy goes from "green tests" to "production is throwing 500s during the symlink window".

---

## Design system

Pave ships a design system. Use it. Adding a new color, button variant, or border radius is almost always the wrong call, because every visual decision should trace back to a CSS custom property in `static/css/source.css`.

Concretely, do not:

- Add a fourth button variant. There are three: Primary, Secondary, Destructive. If you cannot decide, it is Secondary.
- Introduce a new color outside the violet/slate/zinc/semantic palette.
- Use `rounded-xl` or larger on interactive components. Radii are 4px, 6px, 8px.
- Set `font-family` inline or link Google Fonts at runtime. Inter, Newsreader, and IBM Plex Mono are self-hosted under `static/fonts/`.
- Hardcode Tailwind color classes (`bg-zinc-900`) instead of the token variables (`bg-[--bg-surface]`).
- Use `font-bold` (700) anywhere in the UI. Semibold (600) is the ceiling for headings.
- Add `transition` styles inline or via JavaScript. HTMX transitions go through the `.htmx-swapping` and `.htmx-added` classes already defined in `source.css`.

The webhook demo at `/webhooks` is the reference page for every component shipped with Pave. When in doubt about how something should look, open that page and copy the pattern. The full design rules are in [docs/components.md](docs/components.md).

---

## Reporting bugs

A useful bug report has three things, in this order:

1. **A short reproduction.** "Run `pave dev`, sign up with an email that already exists, click the resend verification link." Twelve words, three actions. That is the bar.
2. **Expected vs actual.** "Expected: a flash message saying the address is already in use. Actual: 500 page with `IntegrityError` in the logs."
3. **The relevant code path or log line, if you have it.** `app/routers/auth.py:142` is more useful than "somewhere in auth". A traceback or a journald line beats prose.

If the bug only reproduces on a deployed server, include the output of `fab logs` around the failure and note whether the deploy that introduced the regression was the most recent one (`fab rollback` is the fastest way to test that hypothesis in production).

If you can also include the Pave version (`grep version pyproject.toml`), Python version, and OS, even better. But do not let missing context stop you from filing the issue; a sparse report is better than no report.

Security-sensitive bugs should go to the maintainer privately rather than as a public issue. The email is in the LICENSE file.

---

## Suggesting changes to architecture

Open a GitHub Discussion before you write any code. Pave makes a few opinionated calls and PRs that fight those choices end up closed even when the code is good. Save yourself the round trip.

The opinionated calls, briefly:

- No Docker, no Kubernetes, no Node build step. SSH to Ubuntu under systemd.
- Async SQLAlchemy everywhere. Sync `Session` is banned in app code.
- ORM models never cross the HTTP boundary. Every route has an input schema and an output schema, both in `app/schemas/`.
- `pave` for local commands, `fab` for anything that needs SSH. No Makefile.
- One repo, one app, one deploy. Pave is not a microservice scaffold.

For anything that touches more than a handful of files, post a short sketch first:

- What you want to change and why (one paragraph).
- The current behavior and the proposed behavior (a couple of bullet points each).
- The migration path for existing users (if anything is breaking).

You do not need a design doc. A discussion thread with a few replies is plenty. The goal is to catch "we tried that, here is what broke" before you have spent a week on it.

Small refactors that improve readability without changing behavior are welcome as PRs directly. The line between "small refactor" and "architecture change" is judgment, but if you are renaming a directory, moving a concern between layers, or changing how a subsystem is wired in `app/main.py`, it is the second one.

---

## Code of conduct

Be kind. Disagree about the code, not the person. Assume the other person is trying to make Pave better, even when their PR is rough or their issue is terse.

Harassment and discrimination of any kind are not welcome here. That includes the obvious (slurs, threats, sustained personal attacks) and the less obvious (dismissive language about someone's experience level, deliberate misgendering, gatekeeping). One warning, then a ban.

If something feels off and you are not sure whether to flag it, flag it. Email the maintainer privately rather than calling it out in a public thread. We will figure out the right response together.

This applies to issues, PRs, discussions, and any other Pave space. It also applies to private DMs from people you met through this project: harassment off-platform is still harassment, and we will treat it as such.

---

## Thanks

Every typo fix, every doc clarification, every "this error message was confusing" issue makes Pave better for the next person who clones it. None of it is too small to ship.
