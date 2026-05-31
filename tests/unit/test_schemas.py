import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.user import PasswordReset, UserMe, UserPublic, UserSignup


def test_signup_requires_valid_email() -> None:
    with pytest.raises(ValidationError):
        UserSignup(name="A", email="not-an-email", password="x")


def test_password_reset_rejects_mismatch() -> None:
    with pytest.raises(ValidationError):
        PasswordReset(token="t", password="aaaaaaaa", confirm_password="bbbbbbbb")


def test_password_reset_accepts_match() -> None:
    r = PasswordReset(token="t", password="aaaaaaaa", confirm_password="aaaaaaaa")
    assert r.password == "aaaaaaaa"


def test_user_public_has_no_secret_fields() -> None:
    fields = set(UserPublic.model_fields)
    assert "password_hash" not in fields
    assert "provider_id" not in fields


def test_user_me_extends_public_without_secrets() -> None:
    fields = set(UserMe.model_fields)
    assert "is_active" in fields  # extended view
    assert "password_hash" not in fields
    assert "provider_id" not in fields


def test_user_public_from_orm_attributes() -> None:
    class FakeUser:
        id = uuid.uuid4()
        name = "Ada"
        email = "ada@example.com"
        avatar_url = None
        email_verified_at = None
        created_at = datetime.now(UTC)

    dto = UserPublic.model_validate(FakeUser())
    assert dto.email == "ada@example.com"


def test_paginated_response_is_generic() -> None:
    page = PaginatedResponse[MessageResponse](
        items=[MessageResponse(message="hi")],
        page=1,
        per_page=20,
        total=1,
        pages=1,
    )
    assert page.items[0].message == "hi"
