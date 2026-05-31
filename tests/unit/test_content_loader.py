"""ContentLoader: frontmatter parsing, markdown rendering, blog rules.

Each test builds a throwaway content tree under tmp_path so the loader is
exercised in isolation from the real `content/` directory.
"""

from pathlib import Path

from app.utils.content import ContentLoader


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def _loader(tmp_path: Path) -> ContentLoader:
    (tmp_path / "pages").mkdir(parents=True, exist_ok=True)
    (tmp_path / "blog").mkdir(parents=True, exist_ok=True)
    return ContentLoader(tmp_path)


def test_page_frontmatter_and_markdown(tmp_path: Path) -> None:
    _write(
        tmp_path / "pages" / "about.md",
        "---\ntitle: About Pave\ndescription: who we are\n---\n\n"
        "# Hello\n\nA *paragraph* with `code`.\n",
    )
    loader = _loader(tmp_path)

    page = loader.get_page("about")
    assert page is not None
    assert page.slug == "about"
    assert page.title == "About Pave"
    assert page.description == "who we are"
    assert "<h1>Hello</h1>" in page.html
    assert "<em>paragraph</em>" in page.html


def test_unpublished_is_hidden(tmp_path: Path) -> None:
    _write(
        tmp_path / "pages" / "secret.md",
        "---\ntitle: Secret\npublished: false\n---\n\nhidden\n",
    )
    loader = _loader(tmp_path)

    assert loader.get_page("secret") is None
    assert all(p.slug != "secret" for p in loader.pages())


def test_published_defaults_true_when_absent(tmp_path: Path) -> None:
    _write(tmp_path / "pages" / "terms.md", "---\ntitle: Terms\n---\n\nok\n")
    loader = _loader(tmp_path)

    assert loader.get_page("terms") is not None


def test_blog_slug_and_date_from_filename(tmp_path: Path) -> None:
    _write(
        tmp_path / "blog" / "2026-04-24-launch.md",
        "---\ntitle: Launch\n---\n\nWe shipped.\n",
    )
    loader = _loader(tmp_path)

    post = loader.get_post("launch")
    assert post is not None
    assert post.slug == "launch"
    assert post.date is not None
    assert (post.date.year, post.date.month, post.date.day) == (2026, 4, 24)


def test_posts_sorted_newest_first_and_exclude_drafts(tmp_path: Path) -> None:
    _write(
        tmp_path / "blog" / "2026-01-01-old.md",
        "---\ntitle: Old\n---\n\nold\n",
    )
    _write(
        tmp_path / "blog" / "2026-05-01-new.md",
        "---\ntitle: New\n---\n\nnew\n",
    )
    _write(
        tmp_path / "blog" / "2026-06-01-draft.md",
        "---\ntitle: Draft\npublished: false\n---\n\ndraft\n",
    )
    loader = _loader(tmp_path)

    slugs = [p.slug for p in loader.posts()]
    assert slugs == ["new", "old"]


def test_reading_time_is_at_least_one_minute(tmp_path: Path) -> None:
    _write(tmp_path / "blog" / "2026-04-24-tiny.md", "---\ntitle: Tiny\n---\n\nhi\n")
    loader = _loader(tmp_path)

    post = loader.get_post("tiny")
    assert post is not None
    assert post.reading_time >= 1


def test_dev_mode_picks_up_edits_without_restart(tmp_path: Path) -> None:
    path = tmp_path / "pages" / "live.md"
    _write(path, "---\ntitle: V1\n---\n\none\n")
    (tmp_path / "blog").mkdir(parents=True, exist_ok=True)
    loader = ContentLoader(tmp_path, dev=True)

    assert loader.get_page("live").title == "V1"  # type: ignore[union-attr]
    _write(path, "---\ntitle: V2\n---\n\ntwo\n")
    assert loader.get_page("live").title == "V2"  # type: ignore[union-attr]
