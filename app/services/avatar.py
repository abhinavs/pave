"""Avatar upload pipeline.

Inputs: raw bytes from a multipart upload plus the user they belong to.
Outputs: a URL the browser can render and the User.avatar_url field can
store. Everything in between - sniff, validate, resize, write, evict the
previous file - is in this module so the router stays a thin HTTP layer.

Why a square 256px PNG: avatars get rendered at 32px in the header chip,
40px in the sessions table, and ~96px on the account page. One image at
2x of the largest surface (256px) covers every retina case with a single
file. PNG keeps an alpha channel for the round-mask and avoids the extra
encoder dependency JPEG progressive mode pulls in. The output is always
PNG regardless of the upload format - we trust what we wrote, not what
the client claimed.

Storage is pluggable through `AvatarStorage`. Today there is one
implementation, the local-disk writer, and that is on purpose: shipping
an S3 client in a starter would buy a config knob nobody has set yet.
The protocol means a deploy that wants S3 can swap the class without
touching the route or the service."""

from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import Path
from typing import Protocol

from PIL import Image, UnidentifiedImageError

from app.models.user import User
from app.settings import settings


# Public surface used by the router and the tests.
class AvatarError(ValueError):
    """Raised when an upload is refused. The message is safe to surface."""


# 256px square covers a 96px @3x display tier with one file.
_OUTPUT_PX = 256
_OUTPUT_FORMAT = "PNG"
_OUTPUT_EXT = ".png"

# We only trust formats Pillow ships a tested decoder for. WEBP is in
# because modern browsers and phones upload it by default; HEIC is out
# because Pillow needs an external plugin for it.
_ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}


class AvatarStorage(Protocol):
    """Write/delete bytes by relative key, return a URL to fetch them.

    Implementations decide where the bytes live. The service never sees
    a path - only a key and the URL it resolves to."""

    def url_for(self, key: str) -> str: ...
    async def write(self, key: str, data: bytes) -> None: ...
    async def delete(self, key: str) -> None: ...


class LocalAvatarStorage:
    """The default storage: writes under settings.avatar_dir.

    The directory must be reachable through the static mount for URLs to
    resolve - that is why the default sits under `static/`. If you move
    it elsewhere, also mount the directory in `app/main.py` (or front it
    with nginx in production)."""

    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root if root is not None else settings.avatar_dir)

    def _path(self, key: str) -> Path:
        # Defence in depth: keys are minted by `_key_for` from a uuid and a
        # hash, so the worst case is a future bug that lets a slash in. We
        # resolve and verify containment so a malformed key cannot escape
        # the avatar root.
        target = (self._root / key).resolve()
        root = self._root.resolve()
        if root not in target.parents and target != root:
            raise AvatarError("invalid avatar key")
        return target

    def url_for(self, key: str) -> str:
        # The avatar_dir setting is a filesystem path; the public URL is
        # the same path read as a URL. For the default `static/uploads/...`
        # the static mount turns this into `/static/uploads/...`.
        return "/" + str(self._root / key).replace("\\", "/")

    async def write(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic-ish write: tmp + replace, so a reader never sees a half
        # file even if the process is killed mid-flush.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    async def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)


def _key_for(user_id: uuid.UUID, data: bytes) -> str:
    """`<user_id>-<short hash>.png`. Hash suffix is the cache-buster: a
    new upload gets a new URL even though the user id is the same, so
    browsers re-fetch immediately instead of holding the old image."""
    digest = hashlib.sha256(data).hexdigest()[:12]
    return f"{user_id}-{digest}{_OUTPUT_EXT}"


def _normalise(raw: bytes, max_bytes: int) -> bytes:
    """Open, validate, crop to a centred square, resize, re-encode as PNG.

    Everything inside this function is paranoid on purpose: avatar
    uploads are the first place a hostile user reaches once they have an
    account. Pillow runs the decoder, so the format whitelist plus a max
    pixel area cap keeps a decompression bomb from eating the worker."""
    if len(raw) == 0:
        raise AvatarError("empty file")
    if len(raw) > max_bytes:
        raise AvatarError(
            f"image too large (max {max_bytes // 1024} KiB)"
        )

    try:
        # `verify` consumes the stream, so we open twice - once to verify
        # the structure, once to actually use the image.
        Image.open(io.BytesIO(raw)).verify()
        opened: Image.Image = Image.open(io.BytesIO(raw))
    except (UnidentifiedImageError, OSError) as exc:
        raise AvatarError("not a recognised image") from exc

    if opened.format not in _ALLOWED_FORMATS:
        raise AvatarError(f"unsupported format: {opened.format}")

    # Cap the pixel area to defang a decompression bomb that satisfied
    # the byte-size check (a tiny zlib payload can decode to 50000x50000).
    if opened.width * opened.height > 25_000_000:
        raise AvatarError("image dimensions too large")

    # Centre crop to a square so the resize does not distort.
    short = min(opened.width, opened.height)
    left = (opened.width - short) // 2
    top = (opened.height - short) // 2
    img: Image.Image = opened.crop((left, top, left + short, top + short))
    img = img.resize((_OUTPUT_PX, _OUTPUT_PX), Image.Resampling.LANCZOS)

    # Convert to RGBA so the PNG has a stable channel layout regardless
    # of input. Round-mask CSS expects alpha to be present.
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    out = io.BytesIO()
    img.save(out, format=_OUTPUT_FORMAT, optimize=True)
    return out.getvalue()


def _is_local_avatar(url: str | None, storage: LocalAvatarStorage) -> bool:
    """Only local files are ours to delete. An avatar_url from an OAuth
    provider (Google CDN, GitHub-hosted gravatar) gets replaced by the
    upload but never DELETEd: that would 404 a third party we do not own."""
    if not url:
        return False
    prefix = storage.url_for("").rstrip("/")  # e.g. "/static/uploads/avatars"
    return url.startswith(prefix + "/")


def _key_from_url(url: str, storage: LocalAvatarStorage) -> str:
    """Inverse of `url_for`: pull the key out of a stored avatar URL."""
    prefix = storage.url_for("").rstrip("/") + "/"
    return url[len(prefix):]


async def replace_for_user(
    user: User,
    raw: bytes,
    *,
    storage: AvatarStorage | None = None,
    max_bytes: int | None = None,
) -> str:
    """Process `raw`, write the new file, evict the previous one if it
    was a local upload, mutate `user.avatar_url` in place, return the URL.

    The caller is responsible for committing the session - this function
    treats the file system as the side effect it has to make durable, and
    leaves the database for the route handler to flush."""
    storage = storage or LocalAvatarStorage()
    max_bytes = max_bytes if max_bytes is not None else settings.avatar_max_bytes
    processed = _normalise(raw, max_bytes=max_bytes)
    key = _key_for(user.id, processed)
    await storage.write(key, processed)
    new_url = storage.url_for(key)
    # Best-effort cleanup of the previous file. If it was an OAuth URL,
    # leave it alone; if it was a local file with the same key (a
    # re-upload of the exact same bytes), skip the delete too.
    old = user.avatar_url
    if (
        isinstance(storage, LocalAvatarStorage)
        and _is_local_avatar(old, storage)
        and old != new_url
    ):
        assert old is not None  # narrowed by _is_local_avatar
        await storage.delete(_key_from_url(old, storage))
    user.avatar_url = new_url
    return new_url


async def remove_for_user(
    user: User,
    *,
    storage: AvatarStorage | None = None,
) -> None:
    """Clear the avatar field and delete the underlying file if local."""
    storage = storage or LocalAvatarStorage()
    if isinstance(storage, LocalAvatarStorage) and _is_local_avatar(
        user.avatar_url, storage
    ):
        assert user.avatar_url is not None
        await storage.delete(_key_from_url(user.avatar_url, storage))
    user.avatar_url = None
