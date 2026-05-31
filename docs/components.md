# Components

Pave ships a Jinja + HTMX component kit at `templates/_components/`. You include them with `{% include %}` (or via the `_partials` pattern for HTMX responses). They share a small set of CSS design tokens so the whole app looks consistent without a CSS framework lock-in.

No JavaScript build. No npm install. The Tailwind binary ships as a standalone executable; everything else is server-rendered HTML and HTMX attributes.

## The kit

| Component | What it is | File |
|---|---|---|
| alert | Inline status banners (info, success, warning, error) | `_components/alert.html` |
| badge | Pill labels for status and counts | `_components/badge.html` |
| button | Primary, secondary, destructive | `_components/button.html` |
| card | Bordered content container | `_components/card.html` |
| checkbox | Styled checkbox with label | `_components/checkbox.html` |
| confirm | Inline "Are you sure?" with HTMX swap | `_components/confirm.html` |
| divider | Section break | `_components/divider.html` |
| dropdown | Click-to-open menu | `_components/dropdown.html` |
| empty_state | Friendly "nothing here yet" block | `_components/empty_state.html` |
| form | Form with inline error rendering | `_components/form.html` |
| icon | SVG icon from a sprite | `_components/icon.html` |
| infinite_scroll | HTMX-driven "load more on scroll" | `_components/infinite_scroll.html` |
| input | Labelled text input with error slot | `_components/input.html` |
| layout_sidebar | Two-column app shell | `_components/layout_sidebar.html` |
| logo | The Pave wordmark (replace before launch) | `_components/logo.html` |
| modal | HTMX-driven dialog | `_components/modal.html` |
| pagination | Page links with HTMX swap | `_components/pagination.html` |
| sse_status | Live connection indicator for SSE pages | `_components/sse_status.html` |
| switch | Toggle switch | `_components/switch.html` |
| table | Hover-highlighted table | `_components/table.html` |
| tabs | HTMX-loaded tab content | `_components/tabs.html` |
| theme_toggle | Light / dark / system toggle | `_components/theme_toggle.html` |
| toast | Stacked notifications wired to `HX-Trigger` | `_components/toast.html` |

The reference page for all of them is `/webhooks` in the running app. Open it after `pave dev` and read the source of `templates/webhooks/list.html` to see the kit used together.

---

## Using a component

Jinja's `with` block scopes the variables to the include, which keeps call sites self-documenting.

```jinja
{% with kind="primary", label="Save", type="submit" %}
  {% include "_components/button.html" %}
{% endwith %}
```

Each component file documents its parameters in a comment at the top. Read it once, then copy-paste.

A card with a heading and body:

```jinja
{% with title="Snippets", body="Three saved this week." %}
  {% include "_components/card.html" %}
{% endwith %}
```

---

## Design tokens and theming

`static/css/source.css` defines CSS variables for color, spacing, radius, and typography. Themes override the variables; components use them. To rebrand, change the variables, not the components.

```css
:root {
  --bg-surface: ...;
  --text-default: ...;
  --primary-500: ...;
  --radius-md: 6px;
  --font-sans: "Inter", system-ui, sans-serif;
  --font-serif: "Newsreader", ui-serif, Georgia, serif;
  --font-mono: "IBM Plex Mono", ui-monospace, monospace;
}

[data-theme="dark"] { /* dark overrides */ }
```

Dark mode is the default (`<html data-theme="dark">`). Design components in dark mode first; light mode is a complete alternate, not an afterthought. The `theme_toggle` component flips `data-theme` on `<html>` and persists the choice; `system` follows `prefers-color-scheme`.

**Three color tiers, one semantic layer.**

- Primary (violet) - actions, interactive elements, active states.
- Secondary (slate) - supporting structure, secondary actions, borders.
- Tertiary (zinc) - neutral surfaces, backgrounds, dividers, muted text.
- Semantic - error (red), warning (amber), success (green), info (blue). Status only, never decorative.

Use the CSS variables, not raw Tailwind palette values:

```html
<!-- Correct -->
<div class="bg-[--bg-surface] border border-[--border-subtle]">

<!-- Wrong: hard-codes a color outside the token system -->
<div class="bg-zinc-900 border border-zinc-700">
```

**Three button variants, no more.**

- Primary: `bg-primary-500 text-white hover:bg-primary-600`
- Secondary: `bg-transparent border border-[--border-muted] hover:bg-[--bg-hover]`
- Destructive: `border border-error/30 text-error hover:bg-error/10`

If you find yourself wanting a fourth variant, the answer is Secondary.

**Typography.** Inter for UI, Newsreader for display headings and brand copy, IBM Plex Mono for code and IDs. All three are self-hosted woff2s under `static/fonts/`. Never link Google Fonts at runtime. Body at `text-sm` or `text-base`, semibold (600) is the heading ceiling, never bold.

**Radius.** `rounded-sm` (4px), `rounded-md` (6px), `rounded-lg` (8px). Nothing larger on interactive components.

**Motion.** 100ms for hover/focus, 150ms for state changes, 200ms for panel/toast transitions. No slide, bounce, or spring animations.

---

## HTMX patterns

The five patterns below cover most interactive pages. Each one has a working example in the repo.

### Live search

A search box that updates a table as you type. No SPA, no JSON.

```jinja
<input
  type="text"
  name="q"
  placeholder="Search webhooks"
  hx-get="/webhooks/search"
  hx-trigger="input changed delay:200ms, search"
  hx-target="#rows"
  hx-swap="innerHTML"
/>

<table>
  <tbody id="rows">
    {% include "_partials/webhook_rows.html" %}
  </tbody>
</table>
```

The server returns the `<tr>` rows, not a full page. The partial lives at `templates/_partials/webhook_rows.html`. The matching route is `GET /webhooks/search` in `app/routers/webhooks.py`.

**Why this pattern.** Two routes, one query: the full-page route renders the partial as part of the layout, the partial route renders just the rows. Same code path, different surface.

### Infinite scroll

```jinja
{% for item in items %}
  <li>{{ item.title }}</li>
{% endfor %}

{% if has_more %}
  <li
    hx-get="/items?cursor={{ next_cursor }}"
    hx-trigger="revealed"
    hx-swap="outerHTML"
  >Loading...</li>
{% endif %}
```

The last `<li>` self-replaces with the next page when scrolled into view. `revealed` is a built-in HTMX trigger.

### Modal

```jinja
<button
  hx-get="/snippets/new"
  hx-target="#modal-root"
  hx-swap="innerHTML"
>New snippet</button>

<div id="modal-root"></div>
```

The route returns the modal markup; the `modal` component handles backdrop, focus trap, and `Escape` close. Submit the form inside the modal with `hx-post`; on success, return an empty body plus `HX-Trigger: closeModal`.

### Toast

Set the `HX-Trigger` header on any response. Do not put toast HTML in the response body.

```python
response.headers["HX-Trigger"] = json.dumps({
    "showToast": {"message": "Saved.", "type": "success"}
})
```

The base template's `toast` component listens for `showToast` and stacks them with auto-dismiss.

### Confirm

For destructive actions, use the `confirm` component instead of a JavaScript `confirm()` dialog. It swaps in an inline "Are you sure?" block in place of the trigger, keeping the user's context.

```jinja
{% include "_components/confirm.html" with action_url="/snippets/" ~ s.id ~ "/delete", label="Delete" %}
```

---

## Form errors

Forms in Pave return HTTP 200 with the form re-rendered on validation failure, not 422. HTMX only swaps content for 2xx responses; a 422 would leave the user staring at an unchanged form. The `form` component renders inline errors when an `errors` dict is in the template context.

```python
@router.post("/snippets/new")
async def create_snippet_form(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    try:
        data = SnippetCreate(**form)
    except ValidationError as e:
        return templates.TemplateResponse(
            request,
            "snippets/_partials/form.html",
            {"errors": {err["loc"][0]: err["msg"] for err in e.errors()}, "values": dict(form)},
            status_code=200,  # HTMX swaps on 2xx
        )
    # ... happy path
```

---

## Building your own component

When you reach for a component that does not exist, create it in `templates/_components/`:

- One file per component.
- Top-of-file comment documenting parameters.
- Use design tokens, not hard-coded colors.
- If it has HTMX behavior, document the routes it expects.

Skeleton:

```jinja
{#
  Usage:
    {% with title="...", action="..." %}
      {% include "_components/banner.html" %}
    {% endwith %}

  Required: title, action (url)
  Optional: kind ("info"|"warning"), dismissible (bool)
#}
<div class="banner banner--{{ kind|default('info') }}">
  <p>{{ title }}</p>
  {% if action %}
    <a href="{{ action }}" class="banner__cta">Open</a>
  {% endif %}
</div>
```

---

## Where to look for examples

- **`/webhooks` page** - table, badge, input (live search), empty_state, pagination, toast.
- **`/auth/*` pages** - form, input, button, alert in the auth flow.
- **`/account` page** - card, switch, theme_toggle, modal.

When in doubt, copy from the closest existing page and edit. Pave's HTML is meant to be readable.
