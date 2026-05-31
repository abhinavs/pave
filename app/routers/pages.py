"""Static markdown pages plus the sitemap.

The `/{slug}` route is a root-level catch-all, so this router must be the
last one included in `app/main.py`: anything more specific (/, /blog,
/auth/..., /webhooks/...) has to be registered first or it gets shadowed.
`/sitemap.xml` is declared before `/{slug}` for the same reason.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.templating import templates
from app.utils.content import content

router = APIRouter(tags=["pages"])


@router.get("/sitemap.xml")
async def sitemap(request: Request) -> Response:
    base = str(request.base_url).rstrip("/")
    return templates.TemplateResponse(
        request,
        "sitemap.xml",
        {"pages": content.pages(), "posts": content.posts(), "base": base},
        media_type="application/xml",
    )


@router.get("/llms.txt")
async def llms_txt(request: Request) -> Response:
    """The proposed llmstxt.org standard - a tiny markdown manifest a
    language model can read to find the prose URLs on a site. Built from
    the same `content` loader the sitemap uses, so new pages and posts
    appear here automatically. Served as text/plain because that is what
    the spec asks for and what curl-like clients expect."""
    base = str(request.base_url).rstrip("/")
    return templates.TemplateResponse(
        request,
        "llms.txt",
        {"pages": content.pages(), "posts": content.posts(), "base": base},
        media_type="text/plain; charset=utf-8",
    )


@router.get("/{slug}", response_class=HTMLResponse)
async def page(request: Request, slug: str) -> HTMLResponse:
    doc = content.get_page(slug)
    if doc is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "pages/page.html", {"page": doc})
