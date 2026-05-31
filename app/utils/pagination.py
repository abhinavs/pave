"""The one pagination helper. A pure function, no database knowledge.

Callers slice their own already-fetched list. Routes that paginate a query
should `.limit()/.offset()` at the SQL layer and pass the page through; this
helper is for in-memory collections like the blog index.
"""

from math import ceil

from app.schemas.common import PaginatedResponse


def paginate[T](items: list[T], page: int, per_page: int) -> PaginatedResponse[T]:
    total = len(items)
    pages = max(1, ceil(total / per_page)) if per_page > 0 else 1
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    window = items[start : start + per_page]
    return PaginatedResponse(
        items=window,
        page=page,
        per_page=per_page,
        total=total,
        pages=pages,
    )
