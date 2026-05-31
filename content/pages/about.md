---
title: About Pave
description: What Pave is and why it exists.
published: true
---

Pave is a production starting point for full-stack Python web apps. It is
opinionated on purpose: async SQLAlchemy, explicit DTO schemas, HTMX over a
JavaScript build, Soniq for background jobs, ruff for lint and format, mypy
strict on `app/`, a `pave` CLI for local work, and a Fabric deploy pipeline
you can read end to end.

The goal is simple. The day you clone Pave, you should be able to ship a real
feature, not spend a week wiring up auth, migrations, a job queue, and a
deploy pipeline first. Those are already here, and they already work
together.

This page itself is a markdown file in `content/pages/`. Editing it changes
the site. No database, no admin screen.
