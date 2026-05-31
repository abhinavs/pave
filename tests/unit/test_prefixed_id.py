"""Prefixed, Stripe-style IDs.

The storage layer stays on native `uuid.UUID` (uuid4). The prefix is a
presentation concern, applied at the schema boundary so URLs and API
responses carry semantic type info (`user_02xH...` rather than a bare
`8400e029-...`).
"""

import uuid
from typing import Annotated

import pytest
from pydantic import BaseModel, ValidationError

from app.utils.prefixed_id import PrefixedUUID, decode, encode

# ---------------------------------------------------------------- codec ----


def test_encode_is_deterministic_and_prefixed() -> None:
    u = uuid.UUID("8400e029-2f4a-7d62-9c5e-1d8a2b3c4d5e")
    s = encode("user", u)
    assert s.startswith("user_")
    # Every uuid is 128 bits, which fits in 22 base62 chars - the encoded
    # body is fixed-width so visual length is predictable.
    assert len(s) == len("user_") + 22
    # Pure idempotence: same input, same output.
    assert encode("user", u) == s


def test_encode_decode_round_trips() -> None:
    u = uuid.uuid4()
    assert decode("user", encode("user", u)) == u


def test_decode_rejects_wrong_prefix() -> None:
    s = encode("user", uuid.uuid4())
    with pytest.raises(ValueError, match="prefix"):
        decode("org", s)


def test_decode_rejects_missing_prefix_separator() -> None:
    with pytest.raises(ValueError):
        decode("user", "useractuallynounderscorehere22ch")


def test_decode_rejects_garbage_body() -> None:
    with pytest.raises(ValueError):
        decode("user", "user_!!!notbase62!!!!!!")


def test_decode_rejects_wrong_length_body() -> None:
    with pytest.raises(ValueError):
        decode("user", "user_tooshort")


# ---------------------------------------------- pydantic integration ----

type UserID = Annotated[uuid.UUID, PrefixedUUID("user")]


class _Payload(BaseModel):
    id: UserID


def test_pydantic_serializes_uuid_with_prefix() -> None:
    u = uuid.uuid4()
    dumped = _Payload(id=u).model_dump()
    assert dumped["id"] == encode("user", u)


def test_pydantic_accepts_prefixed_string_as_input() -> None:
    u = uuid.uuid4()
    parsed = _Payload.model_validate({"id": encode("user", u)})
    assert parsed.id == u


def test_pydantic_accepts_raw_uuid_for_internal_callers() -> None:
    """Internal code that already has a UUID in hand should not need to
    re-encode it to hand it to the schema."""
    u = uuid.uuid4()
    assert _Payload(id=u).id == u


def test_pydantic_rejects_prefixed_string_with_wrong_prefix() -> None:
    s = encode("org", uuid.uuid4())
    with pytest.raises(ValidationError):
        _Payload.model_validate({"id": s})


def test_pydantic_round_trip_via_json() -> None:
    """The most common path: server emits json, client (or another schema)
    parses it back. The string form must survive the loop."""
    u = uuid.uuid4()
    payload = _Payload(id=u)
    again = _Payload.model_validate_json(payload.model_dump_json())
    assert again.id == u
