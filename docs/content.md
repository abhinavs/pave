# Content (markdown blog and pages)

Pave's blog posts and static pages are flat markdown files in `content/`,
parsed at request time and rendered into the same Jinja layout as the rest of
the site. There is no CMS, no admin screen, and no database table behind any
of it.

## The 30-second version

```bash
# A new "About the founders" page, live at /founders.
$EDITOR content/pages/founders.md

# A new blog post, live at /blog/launch-notes.
$EDITOR content/blog/2026-05-27-launch-notes.md

# That is the whole workflow. Commit, push, deploy.
```

Every file is markdown with a small YAML frontmatter block on top:

```markdown
---
title: About Pave
description: What Pave is and why it exists.
published: true
---

Pave is a production starting point for full-stack Python web apps...
```

The loader is `app/utils/content.py`. The routes are `app/routers/pages.py`
and `app/routers/blog.py`. The templates are `templates/pages/page.html` and
`templates/blog/post.html`. That is the entire system.

## Why markdown files, not a CMS

Three reasons.

1. Content is versioned with the code. The same `git log` that tells you
   when a route changed tells you when the privacy policy changed.
2. Content is reviewed in PRs. A typo in your terms or a bad claim in a
   blog post goes through the same review as any other change.
3. Content deploys with the rest of the tree. No second pipeline, no second
   service, no "did the CMS sync?" question after a release.

The trade-off is real: non-developer writers cannot edit the site without
opening a PR. If your marketing team needs to ship copy without engineering
in the loop, swap to a CMS. For a small team where the people writing the
copy already write code, this is the lighter setup.

## Static pages (`content/pages/`)

A page is just a markdown file. The filename without `.md` is the slug.

```bash
content/pages/about.md         # served at GET /about
content/pages/privacy.md       # served at GET /privacy
content/pages/founders.md      # served at GET /founders
```

The page route is a root-level catch-all in `app/routers/pages.py`:

```python
@router.get("/{slug}", response_class=HTMLResponse)
async def page(request: Request, slug: str) -> HTMLResponse:
    doc = content.get_page(slug)
    if doc is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "pages/page.html", {"page": doc})
```

Because `/{slug}` is a catch-all, the pages router is included last in
`app/main.py`. Anything more specific (`/`, `/blog`, `/auth/...`) has to be
registered first or it gets shadowed.

Minimum viable page:

```markdown
---
title: Founders
description: Who built this.
published: true
---

## The team

A short paragraph or two.
```

## Blog posts (`content/blog/`)

Blog filenames carry a date prefix. The date orders the index. The slug
after the date is the URL.

```bash
content/blog/2026-04-24-welcome.md        # GET /blog/welcome
content/blog/2026-05-27-launch-notes.md   # GET /blog/launch-notes
```

The blog has three routes in `app/routers/blog.py`:

- `GET /blog` - paginated index, 10 posts per page
- `GET /blog/{slug}` - a single post
- `GET /blog/rss.xml` - the feed

Order matters here too: `/blog/rss.xml` is declared before `/blog/{slug}` so
the feed is not captured as a post slug.

A minimum viable post:

```markdown
---
title: We launched
description: What shipped, what is next.
published: true
date: 2026-05-27
author: The Pave team
---

We shipped. Here is what is in it.
```

The `date` in the filename and the `date` in the frontmatter both work. If
both are present, the frontmatter wins. Reading time is computed from word
count (200 wpm) and shown in the post header.

## Frontmatter reference

| Key | Type | Required | Used by | Notes |
|---|---|---|---|---|
| `title` | string | yes | both | Falls back to the slug if missing. |
| `description` | string | recommended | both | Used as `<meta name="description">` and in the RSS / sitemap. |
| `published` | bool | no (defaults to `true`) | both | `false` hides the file everywhere. |
| `date` | ISO date (`2026-05-27`) | recommended for posts | blog | Sorts the index. Blog filename prefix is used if frontmatter is absent. |
| `author` | string | no | blog | Rendered in the post header byline. |

Anything else you add to frontmatter is ignored. The dataclass in
`app/utils/content.py` (`Doc`) defines the only fields the templates can
read. If you need a new field, add it there.

## Drafts and unpublished content

Set `published: false` to keep a file out of the site:

```markdown
---
title: Half-written draft
published: false
---

still thinking about this...
```

A file with `published: false` is excluded from every list (`/blog`, the
sitemap, `llms.txt`) and the direct URL returns 404. This is true in both
local dev and production. There is no "preview drafts when DEBUG=true" mode.

In practice, the workflow is:

- Local: write with `published: true` (or omit the field), preview at the
  URL, do not commit until it is ready.
- Branch: open a PR. Reviewers see the file in the diff.
- Production: merge to ship.

If you want a "scheduled publish", give the post a future date prefix in the
filename and do not merge the PR until that date. There is no scheduler.

## Images and assets

Put images in `static/` and reference them by URL:

```markdown
![Architecture diagram](/static/images/architecture.png)
```

There is no upload UI. Drop the file into the repo like any other asset.
For posts that need a lot of imagery, a subdirectory like
`static/images/blog/2026-05-27/` keeps things tidy. The convention is yours;
the loader does not care.

## What you can write in markdown

The loader uses `markdown-it-py` configured as CommonMark plus two
extensions:

- Tables (GFM-style)
- Strikethrough (`~~like this~~`)

`linkify` is intentionally not enabled (it would pull in `linkify-it-py`,
which Pave does not ship). Bare URLs are not auto-linked; wrap them in
`<url>` or use a real `[text](url)` link.

Code fences with a language hint are highlighted with Pygments:

````markdown
```python
def hello() -> str:
    return "world"
```
````

Pygments writes class names, not inline styles. The classes are already
covered by `static/css/source.css`. Code blocks with no language hint or an
unknown language fall back to plain escaped `<pre><code>`.

Raw HTML in markdown is passed through (CommonMark default). The content is
rendered with `| safe` in the template, so anything you write in the file
reaches the browser. The content lives in the repo and is reviewed in PRs,
so this is fine; do not feed user-submitted markdown through this loader.

## Limitations, honestly

What this system does not do, and what to reach for instead:

- **No image management UI.** Image paths are written by hand. If you want
  drag-and-drop uploads, you want a CMS.
- **No draft preview workflow.** A `published: false` file is hidden in
  every environment. Preview by toggling the flag locally; ship by merging
  the PR.
- **No scheduled publish.** Use a dated filename and merge the PR on the
  day. If you need real scheduling, a Soniq job that flips a flag in a
  database row is the next step up - but at that point you have left this
  system.
- **No rich editor.** It is a text editor and markdown.
- **No multi-author permissions, no roles, no comments, no analytics.** All
  of that is a CMS feature set, not this.
- **Content is rendered on every request.** Files are cached in memory in
  production (one parse on the first hit per process). In `DEBUG=true` the
  cache is bypassed so edits show up without restarting the server.

When to swap to a CMS: a non-engineer needs to publish without a PR; you
need draft previews via shared URL; you have more than a few hundred
posts; or you need workflows like scheduled publish, review queues, or
roles. Until then, files in `content/` is the cheaper answer.

## Testing a new page renders

```bash
pave dev
# Open http://localhost:8000/founders (or /blog/your-post)
```

That is the entire test loop. `pave dev` runs uvicorn with reload plus the
Tailwind watcher, and the content loader bypasses its cache in debug, so
saving the markdown file and refreshing the browser is enough.

## How content is deployed

Content is part of the repo. It ships in the release snapshot along with
everything else when `fab production deploy` runs (it is tracked, so
`git archive` includes it). There is no separate publish step, no content
build, no cache invalidation to wait on. Once the release symlink flips, the
new files are live.

If you only changed a markdown file, the deploy still runs the full
`fab validate` (ruff, mypy, tests) before shipping. That is intentional:
the gate is the gate. If you need a copy-only fast path, add one as a
Fabric task; do not weaken the default deploy.

## What to build next

Things that would fit naturally on top of this system, in rough order of
usefulness:

- A `pave new-post "My Title"` command that scaffolds a dated filename and
  the frontmatter block. Belongs in `app/cli.py`.
- Per-tag indexes (`/blog/tags/{tag}`). Add a `tags: [a, b]` frontmatter
  field, extend `Doc`, add a route. The loader already does most of the
  work.
- Open Graph image fields in frontmatter, picked up by `base.html`.
- A simple search index built at startup from the in-memory documents.

If any of these grow past a few hundred lines, that is a signal you have
outgrown markdown-in-the-repo and a real CMS is the right call.
