"""Stripe-style prefixed IDs (`user_02xHRi...`, `evt_QrK9...`).

The database stays on native `uuid.UUID` (uuid4) - the prefix and the
base62 encoding are a presentation concern, applied at the Pydantic
schema boundary so URLs, logs, and API responses carry a semantic type
hint without changing how rows are stored or joined.

Why base62: lowercase + uppercase + digits, no `_`, `-`, or `+`, so the
encoded body is URL-safe and the single `_` after the prefix is an
unambiguous separator. Why fixed length: a UUID is exactly 128 bits,
which fits in 22 base62 characters, so the visual width of every ID of
a given type is identical.

Use it from a schema like this:

    from typing import Annotated, TypeAlias
    from uuid import UUID
    from app.utils.prefixed_id import PrefixedUUID

    UserID: TypeAlias = Annotated[UUID, PrefixedUUID("user")]

    class UserPublic(BaseModel):
        id: UserID
        ...

Routes that need to accept the public form on a path parameter can call
`decode("user", raw_path_arg)` and let the resulting `ValueError` turn
into a 404 / 400.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema

# Standard base62 alphabet. Order matters - changing it changes the
# encoding, so any IDs written to logs or shipped to clients become
# undecodable. Treat this as an interface contract.
_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_BASE = 62
_INDEX = {ch: i for i, ch in enumerate(_ALPHABET)}

# 128 bits / log2(62) rounds up to 22 chars. We left-pad to this width
# so an all-zero UUID encodes to twenty-two "0"s rather than a single
# "0", which keeps the visible length constant.
_BODY_LEN = 22


def _b62_encode(n: int) -> str:
    if n == 0:
        return _ALPHABET[0] * _BODY_LEN
    out: list[str] = []
    while n > 0:
        n, rem = divmod(n, _BASE)
        out.append(_ALPHABET[rem])
    out.reverse()
    return "".join(out).rjust(_BODY_LEN, _ALPHABET[0])


def _b62_decode(s: str) -> int:
    n = 0
    for ch in s:
        try:
            n = n * _BASE + _INDEX[ch]
        except KeyError as exc:
            raise ValueError(f"invalid base62 character: {ch!r}") from exc
    return n


def encode(prefix: str, value: uuid.UUID) -> str:
    """Render a UUID as `<prefix>_<22-char base62>`."""
    return f"{prefix}_{_b62_encode(value.int)}"


def decode(prefix: str, value: str) -> uuid.UUID:
    """Parse a `<prefix>_<22-char base62>` string back to a UUID.

    Raises `ValueError` on a wrong prefix, a missing separator, a
    body that is not exactly 22 base62 characters, or an encoded
    value that exceeds 128 bits."""
    sep = f"{prefix}_"
    if not value.startswith(sep):
        raise ValueError(f"expected prefix {prefix!r}, got {value!r}")
    body = value[len(sep) :]
    if len(body) != _BODY_LEN:
        raise ValueError(
            f"expected a {_BODY_LEN}-char body after {prefix!r}, got {len(body)}"
        )
    n = _b62_decode(body)
    if n.bit_length() > 128:
        raise ValueError("decoded value exceeds 128 bits")
    return uuid.UUID(int=n)


@dataclass(frozen=True)
class PrefixedUUID:
    """Pydantic metadata marker that prefixes a `UUID` field on the wire.

    Used as the second arg of `Annotated[UUID, PrefixedUUID("user")]`.
    Implements the Pydantic v2 metadata protocol so input accepts either
    a raw UUID (or UUID string, for ORM round-trips) or the public
    prefixed form, and output always emits the prefixed form."""

    prefix: str

    def __get_pydantic_core_schema__(
        self,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        prefix = self.prefix

        def _validate(v: object) -> uuid.UUID:
            if isinstance(v, uuid.UUID):
                return v
            if isinstance(v, str):
                # Prefixed form wins when the prefix is present;
                # otherwise fall through to a bare UUID parse so the
                # schema can also round-trip raw uuids from the ORM.
                if v.startswith(f"{prefix}_"):
                    return decode(prefix, v)
                try:
                    return uuid.UUID(v)
                except ValueError as exc:
                    raise ValueError(
                        f"expected {prefix!r}-prefixed id or raw UUID, got {v!r}"
                    ) from exc
            raise ValueError(f"cannot coerce {type(v).__name__} to a UUID")

        def _serialize(v: uuid.UUID) -> str:
            return encode(prefix, v)

        return core_schema.no_info_plain_validator_function(
            _validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                _serialize,
                return_schema=core_schema.str_schema(),
                when_used="always",
            ),
        )
