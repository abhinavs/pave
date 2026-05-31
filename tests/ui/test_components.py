"""Every reusable component in templates/_components/ renders.

Components are standalone Jinja partials (no `{% extends %}`) so they can be
`{% include %}`d anywhere. Each is rendered here with a representative
context and checked for its defining marker and for design-system tokens
rather than raw Tailwind colours.
"""

import pytest
from jinja2 import Environment

from app.templating import templates

env: Environment = templates.env


def _render(name: str, **ctx: object) -> str:
    return env.get_template(f"_components/{name}").render(**ctx)


def test_table_renders_headers_and_rows() -> None:
    html = _render(
        "table.html",
        columns=["Slug", "Status"],
        rows=[["stripe", "pending"], ["github", "processed"]],
    )
    assert "<table" in html
    assert "<th" in html and "Slug" in html
    assert "stripe" in html and "processed" in html


def test_form_renders_fields_and_inline_errors() -> None:
    html = _render(
        "form.html",
        action="/items/new",
        fields=[{"name": "title", "label": "Title", "type": "text"}],
        errors={"title": "Title is required"},
        submit_label="Create",
    )
    assert 'action="/items/new"' in html
    assert 'name="title"' in html
    assert "Title is required" in html
    assert "Create" in html


def test_toast_listens_for_hx_trigger_event() -> None:
    html = _render("toast.html")
    assert "showToast" in html
    assert "x-data" in html


def test_modal_is_a_dialog() -> None:
    html = _render("modal.html", modal_id="confirm-delete", title="Are you sure?")
    assert 'role="dialog"' in html
    assert "confirm-delete" in html
    assert "Are you sure?" in html


def test_sse_status_connects_to_the_stream() -> None:
    html = _render("sse_status.html", sse_url="/jobs/42/stream")
    assert "sse" in html
    assert "/jobs/42/stream" in html


def test_layout_sidebar_marks_the_active_item() -> None:
    html = _render(
        "layout_sidebar.html",
        nav=[
            {"href": "/a", "label": "Alpha", "active": True},
            {"href": "/b", "label": "Beta", "active": False},
        ],
    )
    assert "Alpha" in html and "Beta" in html
    assert "text-primary-400" in html  # active item tint, per design system


def test_confirm_is_destructive_and_carries_the_message() -> None:
    html = _render(
        "confirm.html",
        action="/items/1/delete",
        label="Delete",
        message="Delete this item?",
    )
    assert "Delete this item?" in html
    assert "/items/1/delete" in html
    assert "text-error" in html  # destructive variant, not a 4th button


def test_pagination_shows_window_and_neighbours() -> None:
    page = {"page": 2, "pages": 3, "per_page": 10, "total": 25}
    html = _render("pagination.html", page=page, base_url="/blog")
    assert "/blog?page=1" in html  # previous
    assert "/blog?page=3" in html  # next
    assert "2" in html


def test_infinite_scroll_loads_the_next_page_when_revealed() -> None:
    html = _render("infinite_scroll.html", next_url="/blog?page=3")
    assert 'hx-get="/blog?page=3"' in html
    assert "revealed" in html


@pytest.mark.parametrize(
    "name",
    [
        "table.html",
        "form.html",
        "toast.html",
        "modal.html",
        "sse_status.html",
        "layout_sidebar.html",
        "confirm.html",
        "pagination.html",
        "infinite_scroll.html",
    ],
)
def test_component_template_exists(name: str) -> None:
    assert env.get_template(f"_components/{name}") is not None
