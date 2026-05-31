"""UI smoke tests for the layout and content pages.

These pin plumbing only - mounted routes, structural layout attributes,
auth-state surfacing, and where markdown content reaches the user. Hero
copy, marketing language, and gallery section names are deliberately
not pinned: this is a template, and the first thing a user does is
rewrite that copy. A test suite that breaks on cosmetic edits trains
people to delete tests instead of reading them."""

from httpx import AsyncClient


async def test_index_ok_anonymous(async_client: AsyncClient) -> None:
    resp = await async_client.get("/")
    assert resp.status_code == 200
    body = resp.text
    # anonymous visitors are offered a way in
    assert "/auth/login" in body
    assert "/auth/signup" in body


async def test_index_shows_name_when_authenticated(
    authenticated_client: AsyncClient,
) -> None:
    resp = await authenticated_client.get("/")
    assert resp.status_code == 200
    # the test_user fixture is named "Ada"
    assert "Ada" in resp.text


async def test_index_is_full_html_document(async_client: AsyncClient) -> None:
    resp = await async_client.get("/")
    assert "<html" in resp.text.lower()
    assert "</html>" in resp.text.lower()


async def test_index_ships_favicon_and_theme_boot(async_client: AsyncClient) -> None:
    """Every layout has to wire the favicon link and the inline theme boot
    script that prevents a flash of the wrong palette."""
    resp = await async_client.get("/")
    body = resp.text
    assert "/static/img/favicon.svg" in body
    assert "pave-theme" in body  # the localStorage key the boot script reads


async def test_components_gallery_is_reachable(async_client: AsyncClient) -> None:
    """The /components page is the design system index. The route has to
    be mounted and reachable anonymously - the specific sections it lists
    are not pinned because they evolve with the design system."""
    resp = await async_client.get("/components")
    assert resp.status_code == 200


async def test_base_layout_wires_the_mobile_drawer(
    async_client: AsyncClient,
) -> None:
    """The hamburger trigger and the drawer panel have to agree on a
    handle so the menu actually opens on small screens. That handle is
    plumbing - the logo's typographic treatment is not."""
    resp = await async_client.get("/")
    body = resp.text
    # the Alpine state name shared by the button and the panel
    assert "navOpen" in body
    # the mobile drawer panel id is wired to the hamburger
    assert 'id="mobile-nav"' in body


async def test_base_layout_surfaces_markdown_pages_in_footer(
    async_client: AsyncClient,
) -> None:
    """The footer is the discovery surface for the markdown-driven static
    pages. If a link drops out here, visitors have no way to reach the
    legal copy short of typing the URL by hand."""
    resp = await async_client.get("/")
    body = resp.text
    assert 'href="/about"' in body
    assert 'href="/privacy"' in body
    assert 'href="/terms"' in body
    # Blog lives in both the mobile drawer and the footer; the footer is
    # the one persistent surface across breakpoints.
    assert body.count('href="/blog"') >= 1


async def test_llms_txt_is_served_as_plain_text(async_client: AsyncClient) -> None:
    """The llmstxt.org manifest is reachable at /llms.txt as text/plain so
    a language model can find it without parsing HTML. We pin the route
    and the content-type only - the body copy is template-driven and the
    first thing a user does after cloning is rewrite it."""
    resp = await async_client.get("/llms.txt")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert resp.text.strip()  # not blank
