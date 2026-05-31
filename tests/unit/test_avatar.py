"""Avatar service tests.

These exercise the pipeline directly - validation, resize, the local
storage, and the replace/remove orchestration - without going through
the HTTP layer. The route's wiring is covered in tests/functional/."""

import io
import uuid
from pathlib import Path

import pytest
from PIL import Image

from app.services.avatar import (
    AvatarError,
    LocalAvatarStorage,
    _normalise,
    prune_previous_avatar,
    remove_for_user,
    replace_for_user,
)


def _png_bytes(
    width: int,
    height: int,
    color: tuple[int, int, int] = (200, 80, 200),
) -> bytes:
    """Mint a PNG of the requested size. The test images are PIL-generated
    so the same code that decodes them in production decodes them here."""
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


class _StubUser:
    """A duck-typed stand-in for app.models.user.User. The service only
    reads .id and writes .avatar_url, so the real ORM model is overkill."""

    def __init__(self, avatar_url: str | None = None) -> None:
        self.id = uuid.uuid4()
        self.avatar_url: str | None = avatar_url


def test_normalise_rejects_empty_bytes() -> None:
    with pytest.raises(AvatarError, match="empty"):
        _normalise(b"", max_bytes=1024)


def test_normalise_rejects_oversize_bytes() -> None:
    raw = _png_bytes(64, 64)
    # Pass a max smaller than the image to trigger the cap.
    with pytest.raises(AvatarError, match="too large"):
        _normalise(raw, max_bytes=len(raw) - 1)


def test_normalise_rejects_non_image() -> None:
    with pytest.raises(AvatarError, match="not a recognised image"):
        _normalise(b"this is plainly not an image", max_bytes=1024)


def test_normalise_resizes_to_256_square_png() -> None:
    raw = _png_bytes(800, 400)  # wide image, will be centre-cropped
    out = _normalise(raw, max_bytes=10_000_000)
    img = Image.open(io.BytesIO(out))
    assert img.format == "PNG"
    assert img.size == (256, 256)
    assert img.mode == "RGBA"  # alpha channel preserved for the round mask


def test_local_storage_writes_and_serves_url(tmp_path: Path) -> None:
    storage = LocalAvatarStorage(tmp_path)
    # url_for renders the disk path as a URL. With an absolute tmp path
    # the URL is also absolute - which is what the static mount needs.
    url = storage.url_for("hello.png")
    assert url.endswith("/hello.png")
    assert str(tmp_path) in url


async def test_local_storage_round_trips_bytes(tmp_path: Path) -> None:
    storage = LocalAvatarStorage(tmp_path)
    payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    await storage.write("a.png", payload)
    assert (tmp_path / "a.png").read_bytes() == payload
    await storage.delete("a.png")
    assert not (tmp_path / "a.png").exists()


async def test_replace_for_user_writes_file_and_sets_url(tmp_path: Path) -> None:
    storage = LocalAvatarStorage(tmp_path)
    user = _StubUser()
    raw = _png_bytes(300, 300)

    url = await replace_for_user(user, raw, storage=storage, max_bytes=10_000_000)

    assert user.avatar_url == url
    # The URL points at a file that exists on disk.
    on_disk = list(tmp_path.glob("*.png"))
    assert len(on_disk) == 1
    assert on_disk[0].name in url


async def test_replace_for_user_does_not_delete_old_file(tmp_path: Path) -> None:
    """replace_for_user must NOT delete the previous file: if the caller's
    commit then fails, the rolled-back avatar_url would point at a file that
    was already gone. Deletion is deferred to prune_previous_avatar, post-commit."""
    storage = LocalAvatarStorage(tmp_path)
    user = _StubUser()

    await replace_for_user(
        user,
        _png_bytes(300, 300, color=(10, 20, 30)),
        storage=storage,
        max_bytes=10_000_000,
    )
    first_file = next(tmp_path.glob("*.png"))

    await replace_for_user(
        user,
        _png_bytes(300, 300, color=(200, 100, 50)),
        storage=storage,
        max_bytes=10_000_000,
    )

    # Both files still on disk: the old one survives until prune runs.
    assert len(list(tmp_path.glob("*.png"))) == 2
    assert first_file.exists()


async def test_prune_previous_avatar_evicts_old_local_file(tmp_path: Path) -> None:
    storage = LocalAvatarStorage(tmp_path)
    user = _StubUser()

    old_url = await replace_for_user(
        user,
        _png_bytes(300, 300, color=(10, 20, 30)),
        storage=storage,
        max_bytes=10_000_000,
    )
    first_file = next(tmp_path.glob("*.png"))
    new_url = await replace_for_user(
        user,
        _png_bytes(300, 300, color=(200, 100, 50)),
        storage=storage,
        max_bytes=10_000_000,
    )

    # Post-commit cleanup removes only the old file, keeping the live one.
    await prune_previous_avatar(old_url, keep=new_url, storage=storage)

    files = list(tmp_path.glob("*.png"))
    assert len(files) == 1
    assert not first_file.exists()


async def test_prune_previous_avatar_leaves_oauth_url_alone(tmp_path: Path) -> None:
    storage = LocalAvatarStorage(tmp_path)
    # An external CDN url is not ours to delete; prune must no-op without error.
    await prune_previous_avatar(
        "https://lh3.googleusercontent.com/a/x", keep=None, storage=storage
    )


async def test_replace_for_user_leaves_oauth_url_alone(tmp_path: Path) -> None:
    """A previous avatar_url that points at an external CDN (Google,
    GitHub) is not ours to delete - we only replace the field."""
    storage = LocalAvatarStorage(tmp_path)
    user = _StubUser(avatar_url="https://lh3.googleusercontent.com/a/x")

    await replace_for_user(
        user,
        _png_bytes(64, 64),
        storage=storage,
        max_bytes=10_000_000,
    )

    # No exception was raised trying to delete the external URL.
    assert user.avatar_url is not None
    assert user.avatar_url != "https://lh3.googleusercontent.com/a/x"


async def test_remove_for_user_clears_field_and_local_file(tmp_path: Path) -> None:
    storage = LocalAvatarStorage(tmp_path)
    user = _StubUser()
    await replace_for_user(
        user,
        _png_bytes(64, 64),
        storage=storage,
        max_bytes=10_000_000,
    )
    assert list(tmp_path.glob("*.png"))

    await remove_for_user(user, storage=storage)

    assert user.avatar_url is None
    assert not list(tmp_path.glob("*.png"))


async def test_remove_for_user_clears_oauth_field_without_delete(
    tmp_path: Path,
) -> None:
    storage = LocalAvatarStorage(tmp_path)
    user = _StubUser(avatar_url="https://lh3.googleusercontent.com/a/x")

    await remove_for_user(user, storage=storage)

    assert user.avatar_url is None
    # The external URL never existed on our disk - the test passes by not
    # raising.
