# Why Pave?

A short page for the reader still deciding. If you have already cloned the repo, [Getting Started](getting-started.md) is the better next click.

## The 30-second version

Most Python web apps are deployed in one of three ways:

1. **A managed platform** (Heroku, Fly, Render, Railway). Fast to start. You pay per dyno or per build minute, and you inherit the platform's quirks. Migrating off is a project.
2. **Containers on a cloud** (Docker Compose, ECS, GKE). Powerful and portable, but the operational surface is large for a small app. You maintain Docker, a registry, a CI/CD pipeline, an orchestrator, and the app.
3. **Plain Linux** (apt, systemd, Nginx, git over SSH). The oldest path. Reliable, cheap, fast to deploy. The hard part is wiring it up correctly the first time, which is exactly what Pave does for you.

Pave is the third option, pre-wired. You write FastAPI; Pave is the production glue.

---

## What Pave optimises for

In order:

1. **Time from `git clone` to a live URL.** The pre-1.0 number is 15 minutes on a fresh VPS, and most of that is one-time server prep.
2. **Cognitive load you can hold in your head.** One repo. One deploy command. One config file. One log location. Two systemd units.
3. **A path you can read end to end.** `fabfile.py` is short and readable. The deploy is not a black box.
4. **Defaults that survive contact with production.** Health checks, atomic releases, automatic rollback, structured logs, signed sessions, CSRF, HSTS, rate-limited auth.

What Pave does *not* optimise for: a separate frontend build pipeline, a microservice mesh from day one, or a deploy story that needs no SSH key.

---

## Pave vs. the alternatives

|  | Pave | Docker Compose on a VPS | Managed platform | Kubernetes |
|---|---|---|---|---|
| First deploy | ~15 min | ~30-60 min | ~10 min | ~half a day |
| Monthly cost (small app) | $5-$20 VPS | $5-$20 VPS | $20-$200+ | $70+ control plane alone |
| Things to maintain | App, systemd unit, Nginx site | + Docker, Compose file, registry, image build | + vendor account, build config, addon plumbing | + cluster, manifests, ingress, image registry, CI/CD |
| Deploy command | `fab production deploy` | `docker compose pull && up -d` (after CI builds an image) | `git push <platform>` | `kubectl apply` + helm + image push |
| Rollback | Automatic on health-check fail | Manual: `docker compose up <prev-tag>` | Platform UI / CLI | `kubectl rollout undo` |
| Multi-host | Same command, Fabric host list | Compose does not, Swarm/Nomad does | Built in | The whole point |
| Lock-in | None (it is just Linux) | Mild (Compose conventions) | High | Medium-high |
| Good for | Real apps on 1-N VPSes | Teams already on Docker | Side projects, prototypes, no-ops teams | Large fleets |

The right column is not "worse." Kubernetes is the right answer for many teams. Pave is the right answer when the operational surface of Kubernetes is bigger than the app itself, which is most apps most of the time.

---

## Common objections, answered

### "No Docker? Really?"

Really. The argument for Docker on a single-app deployment is reproducibility, and the argument against is operational surface. Pave gets reproducibility from a different angle: a pinned `requirements.txt`, a known Python version, an env schema validated at deploy time, and a release-directory model that keeps every shipped tree intact on the server.

If your team is already on Docker for other reasons, Pave still works. The app is plain Python; you can containerise it in an afternoon. Nothing in the codebase resists it.

### "Won't I outgrow one server?"

Maybe. The honest answer:

- A tuned single VPS running Pave (Postgres on the same host, 4-8 GB RAM) handles a surprising amount of traffic. Most apps will never need more.
- When you do need more, the migration is incremental. Move Postgres to a managed instance. Add a second app server behind a load balancer (Fabric host lists are built for this). Move the worker to its own box. None of these changes require rewriting Pave; they are operational moves on top of the same code.
- You will not hit a "Pave wall" before you hit a "your app needs to be rearchitected" wall. The latter happens first, in every framework.

### "How does this compare to Fly / Render / Railway?"

Managed platforms remove ops work in exchange for monthly cost and a vendor relationship. They are great choices, especially while a project is in the "is this going to work at all" phase.

Pave is the right next step when the platform's pricing starts to bite, when you need something the platform does not offer (custom Postgres extensions, long-running workers, a specific Linux package), or when you want a deploy story you can read in one file.

### "Is SSH-based deploy still safe in 2026?"

Yes, with the standard precautions: key-only auth, a non-root deploy user with narrow sudo, fail2ban, automatic security updates. [deploy.md](deploy.md) walks through all of this. The deploy itself is git over SSH: the server fetches your repo and snapshots a release with `git archive`, the same primitive every "no Docker" deploy tool ultimately uses.

The risk profile of SSH is well understood. The risk profile of a leaked container-registry token is also well understood. Pick the one whose mitigations you would rather audit.

### "What about my React or Vue frontend?"

Pave's UI story is server-rendered Jinja plus HTMX. That covers most internal tools, dashboards, marketing pages, and CRUD apps without a JavaScript build.

If you need a real SPA, the honest answer is that Pave will fight you. You can still use Pave as the API and host the SPA's built assets statically, but you are now running two build systems and the docs assume one. A different starter probably suits you better.

### "Is this just another opinionated boilerplate?"

It is opinionated. The question is whether the opinions are worth holding.

- Async SQLAlchemy 2.0, not Django ORM, because the runtime is async.
- Schemas at every route boundary, not ORM-as-DTO, because the wire shape and the DB shape change for different reasons.
- HTMX, not React, because most pages do not need a SPA.
- Fabric, not Docker, because the deploy is shorter and the file is readable.
- systemd, not supervisord or pm2, because it is already on the server.

If you disagree with one of these, you can swap it. If you disagree with all of them, this is the wrong starter.

### "Who is behind it and is it maintained?"

Pave is built by [Abhinav Saxena](https://github.com/abhinavs) and is currently at `0.0.1` (pre-1.0, the API may still shift). The MIT license means you can fork it. The [production-readiness checklist](production-readiness.md) tracks what is done, what is partial, and what is left.

There is no company behind Pave, no paid tier, and no roadmap toward one. It is open source because the alternative was writing the same FastAPI scaffolding for the fourth time.

---

## When to choose something else

Use Django if you want batteries that include an admin UI out of the box, you do not need async, and you would rather have a 20-year-old framework's stability than a smaller, newer one.

Use a managed platform if your team will never SSH into a server and the cost is justified by the time saved.

Use Kubernetes if you genuinely run a fleet, have multiple teams shipping to shared infrastructure, or have compliance requirements that map cleanly onto cluster primitives.

Use Next.js or Remix if your app is fundamentally a JavaScript application that occasionally talks to a Python service.

Use plain FastAPI if you only need the API layer and you already have your own production toolchain.

Pave is for the case in the middle: a real full-stack Python app, deployed by a small team, on infrastructure they own.

---

## Who Pave is for

- **Solo developers and small teams** who want production defaults without a platform bill.
- **Engineers tired of orchestrator overhead** for apps that do not need orchestration.
- **Rails / Django folks** evaluating async Python who want the same "one command to deploy" feel.
- **Teams ready to leave a managed platform** without rewriting their app.

If that sounds like you, [Getting Started](getting-started.md) takes 15 minutes.
