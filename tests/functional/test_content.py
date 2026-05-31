"""Blog, pages, sitemap and RSS over the real `content/` tree.

These run against the seeded content shipped in the repo, so they also
guard that the seed files stay parseable and published.
"""

from xml.etree import ElementTree

from httpx import AsyncClient


async def test_blog_index_lists_the_welcome_post(
    async_client: AsyncClient,
) -> None:
    resp = await async_client.get("/blog")

    assert resp.status_code == 200
    assert "Welcome" in resp.text


async def test_blog_post_renders(async_client: AsyncClient) -> None:
    resp = await async_client.get("/blog/welcome")

    assert resp.status_code == 200
    assert "Welcome" in resp.text


async def test_unknown_post_is_404(async_client: AsyncClient) -> None:
    resp = await async_client.get("/blog/does-not-exist")

    assert resp.status_code == 404


async def test_static_pages_render(async_client: AsyncClient) -> None:
    for slug in ("about", "privacy", "terms"):
        resp = await async_client.get(f"/{slug}")
        assert resp.status_code == 200, slug


async def test_unknown_page_is_404(async_client: AsyncClient) -> None:
    resp = await async_client.get("/no-such-page")

    assert resp.status_code == 404


async def test_sitemap_is_well_formed_xml(async_client: AsyncClient) -> None:
    resp = await async_client.get("/sitemap.xml")

    assert resp.status_code == 200
    assert "xml" in resp.headers["content-type"]
    root = ElementTree.fromstring(resp.text)
    assert root.tag.endswith("urlset")
    locs = [e.text for e in root.iter() if e.tag.endswith("loc")]
    assert any(loc and loc.endswith("/about") for loc in locs)
    assert any(loc and loc.endswith("/blog/welcome") for loc in locs)


async def test_rss_is_well_formed(async_client: AsyncClient) -> None:
    resp = await async_client.get("/blog/rss.xml")

    assert resp.status_code == 200
    assert "xml" in resp.headers["content-type"]
    root = ElementTree.fromstring(resp.text)
    assert root.tag == "rss"
    titles = [e.text for e in root.iter("title")]
    assert any(t and "Welcome" in t for t in titles)
