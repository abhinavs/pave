"""The blog: an index, individual posts, and an RSS feed.

All three read from the in-memory `content` loader, not the database. Route
order matters: `/blog/rss.xml` is declared before `/blog/{slug}` so the feed
is not captured as a post slug.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.templating import templates
from app.utils.content import content
from app.utils.pagination import paginate

router = APIRouter(tags=["blog"])

_PER_PAGE = 10


@router.get("/blog", response_class=HTMLResponse)
async def blog_index(request: Request, page: int = 1) -> HTMLResponse:
    window = paginate(content.posts(), page=page, per_page=_PER_PAGE)
    return templates.TemplateResponse(
        request,
        "blog/list.html",
        {"posts": window.items, "page": window},
    )


@router.get("/blog/rss.xml")
async def blog_rss(request: Request) -> Response:
    base = str(request.base_url).rstrip("/")
    return templates.TemplateResponse(
        request,
        "blog/rss.xml",
        {"posts": content.posts(), "base": base},
        media_type="application/xml",
    )


@router.get("/blog/{slug}", response_class=HTMLResponse)
async def blog_post(request: Request, slug: str) -> HTMLResponse:
    post = content.get_post(slug)
    if post is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "blog/post.html", {"post": post})
