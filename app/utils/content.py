"""Markdown content loader.

Blog posts and static pages are flat files under `content/`, not database
rows: version-controlled, reviewable, no admin. Files are parsed with
python-frontmatter, rendered with markdown-it-py, and code is highlighted
with Pygments. Results are cached in memory; in debug the cache is bypassed
so edits show up without a restart.

Blog filenames are `YYYY-MM-DD-slug.md`: the date orders the index and the
slug is the URL. Page filenames are just `slug.md`.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import frontmatter
from markdown_it import MarkdownIt
from pygments import highlight  # type: ignore[import-untyped]
from pygments.formatters import HtmlFormatter  # type: ignore[import-untyped]
from pygments.lexers import (  # type: ignore[import-untyped]
    get_lexer_by_name,
    guess_lexer,
)
from pygments.util import ClassNotFound  # type: ignore[import-untyped]

from app.settings import settings

_DATE_PREFIX = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(.+)$")
_WORDS_PER_MINUTE = 200


@dataclass(frozen=True, slots=True)
class Doc:
    """One rendered markdown document, page or post."""

    slug: str
    title: str
    description: str
    published: bool
    date: date | None
    author: str | None
    html: str
    reading_time: int


def _highlight(code: str, lang: str, _attrs: str) -> str:
    try:
        lexer = get_lexer_by_name(lang) if lang else guess_lexer(code)
    except ClassNotFound:
        return ""  # fall back to markdown-it's escaped <pre><code>
    return str(highlight(code, lexer, HtmlFormatter(nowrap=False)))


def _coerce_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


class ContentLoader:
    def __init__(self, base: Path, *, dev: bool = False) -> None:
        self._base = Path(base)
        self._dev = dev
        self._cache: dict[str, dict[str, Doc]] = {}

    def _md(self) -> MarkdownIt:
        # commonmark + tables/strikethrough, but not linkify: linkify would
        # pull in linkify-it-py, a dependency we do not ship.
        md = MarkdownIt("commonmark", {"highlight": _highlight})
        md.enable(["table", "strikethrough"])
        return md

    def _parse(self, path: Path, kind: str) -> Doc:
        post = frontmatter.load(str(path))
        meta = post.metadata
        slug = path.stem
        doc_date: date | None = None

        if kind == "blog":
            match = _DATE_PREFIX.match(slug)
            if match:
                year, month, day, slug = match.groups()
                doc_date = date(int(year), int(month), int(day))

        if "date" in meta:
            doc_date = _coerce_date(meta["date"]) or doc_date

        author = meta.get("author")
        words = len(post.content.split())

        return Doc(
            slug=slug,
            title=str(meta.get("title", slug)),
            description=str(meta.get("description", "")),
            published=bool(meta.get("published", True)),
            date=doc_date,
            author=str(author) if author is not None else None,
            html=self._md().render(post.content),
            reading_time=max(1, round(words / _WORDS_PER_MINUTE)),
        )

    def _docs(self, kind: str) -> dict[str, Doc]:
        if not self._dev and kind in self._cache:
            return self._cache[kind]

        docs: dict[str, Doc] = {}
        directory = self._base / kind
        if directory.is_dir():
            for path in sorted(directory.glob("*.md")):
                doc = self._parse(path, kind)
                docs[doc.slug] = doc

        self._cache[kind] = docs
        return docs

    def pages(self) -> list[Doc]:
        return [d for d in self._docs("pages").values() if d.published]

    def get_page(self, slug: str) -> Doc | None:
        doc = self._docs("pages").get(slug)
        return doc if doc is not None and doc.published else None

    def posts(self) -> list[Doc]:
        published = [d for d in self._docs("blog").values() if d.published]
        return sorted(
            published, key=lambda d: d.date or date.min, reverse=True
        )

    def get_post(self, slug: str) -> Doc | None:
        doc = self._docs("blog").get(slug)
        return doc if doc is not None and doc.published else None


content = ContentLoader(Path("content"), dev=settings.debug)
