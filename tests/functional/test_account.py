"""Account router tests: profile page, avatar upload and remove.

The unit suite in tests/unit/test_avatar.py exercises the service layer
directly. These tests pin the HTTP wiring: auth gate, file handling,
redirects, flash messages. They also redirect AvatarStorage at a tmp
directory through settings so the real `static/uploads/` tree stays
clean across runs."""

import io

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


def _png(size: int = 300) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (size, size), (40, 80, 200)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _isolated_avatar_dir(tmp_path, monkeypatch):
    """Point avatar storage at a tmp dir so the tests do not pile files
    into the real `static/uploads/avatars/` tree. The setting is read at
    LocalAvatarStorage construction time, so patching settings is
    sufficient - no need to rebuild the app."""
    monkeypatch.setattr("app.settings.settings.avatar_dir", str(tmp_path))


async def test_account_page_requires_login(async_client: AsyncClient) -> None:
    resp = await async_client.get("/account")
    assert resp.status_code in (302, 303)
    assert "/auth/login" in resp.headers["location"]


async def test_account_page_renders_for_user(
    authenticated_client: AsyncClient,
) -> None:
    resp = await authenticated_client.get("/account")
    assert resp.status_code == 200
    body = resp.text
    # The plumbing we care about: upload form points back at the right
    # endpoint, and the file input is wired with the multipart enctype.
    assert 'action="/account/avatar"' in body
    assert 'enctype="multipart/form-data"' in body
    assert 'name="file"' in body


async def test_avatar_upload_sets_avatar_url(
    authenticated_client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    files = {"file": ("me.png", _png(), "image/png")}
    resp = await authenticated_client.post("/account/avatar", files=files)
    assert resp.status_code in (302, 303)
    assert "avatar-updated" in resp.headers["location"]

    await db_session.refresh(test_user)
    assert test_user.avatar_url is not None
    # The hash-suffixed filename keeps the URL cache-busting; this is the
    # contract the header chip relies on.
    assert ".png" in test_user.avatar_url


async def test_avatar_upload_rejects_non_image(
    authenticated_client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    files = {"file": ("nope.png", b"this is not an image", "image/png")}
    resp = await authenticated_client.post("/account/avatar", files=files)
    # Validation failure round-trips through the redirect, surfacing the
    # service-layer error message in ?status=error:...
    assert resp.status_code in (302, 303)
    assert "error" in resp.headers["location"]

    await db_session.refresh(test_user)
    assert test_user.avatar_url is None


async def test_avatar_remove_clears_field(
    authenticated_client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    # First upload, so there is something to remove.
    files = {"file": ("a.png", _png(), "image/png")}
    await authenticated_client.post("/account/avatar", files=files)

    resp = await authenticated_client.post("/account/avatar/remove")
    assert resp.status_code in (302, 303)
    assert "avatar-removed" in resp.headers["location"]

    await db_session.refresh(test_user)
    assert test_user.avatar_url is None
