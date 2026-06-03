---
title: About Pave
description: What Pave is, what it believes, and who it is for.
published: true
---

Pave is a production starting point for full-stack Python web apps. The day
you clone it, the parts that usually eat your first week are already here and
already working together: async database access, migrations, email and OAuth
login, a background job worker, a component library, and a deploy pipeline you
can read end to end.

You should be shipping your actual idea on day one, not wiring up the same
plumbing you wired up on the last three projects.

## What you get

- **A FastAPI app on async SQLAlchemy 2.0**, with request-scoped sessions and
  Alembic migrations set up the way they are meant to be set up.
- **Authentication that is finished**, not sketched: email and password,
  Google, and GitHub, with confirmation, password reset, and a session store
  you can revoke per device.
- **Server-rendered HTML with HTMX and Alpine**, so you get interactive pages
  without a JavaScript build step or a single-page-app to maintain.
- **Background jobs on Soniq**, running on the same Postgres your app already
  uses. No Redis, no extra broker to babysit.
- **A real design system** behind a Tailwind build, with tokens, components,
  and a gallery you can browse.
- **A deploy story that ends on a real server.** One Fabric command runs the
  tests, the type checker, the linter, and the migration plan, then ships the
  release to a Linux box over SSH. Rollback is a single command.

## What Pave believes

**Boring infrastructure is a feature.** The interesting part of your project
is your idea. Everything underneath it should be obvious, well-trodden, and
easy to reason about at 2am.

**Fewer moving parts beats more.** No Docker requirement, no Node runtime, no
message broker you did not ask for. The stack is small enough to hold in your
head.

**Opinions you can undo.** Pave makes choices so you do not have to on day
one, but every one of them is small enough to reverse in an afternoon when
your project earns a different answer.

## Who it is for

Pave assumes you are comfortable with Python and want to build a web product
without first becoming a full-time platform engineer. It is a good fit for
solo builders, small teams, and internal tools. It is not trying to be a
framework, and it is not trying to win a benchmark.

This page itself is a markdown file in `content/pages/`. Editing it changes
the site, with no database and no admin screen. That is the whole content
system, and it is the same one your own pages will use.
