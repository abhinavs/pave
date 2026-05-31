import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.utils.prefixed_id import PrefixedUUID

# Public id type for User-shaped schemas. The database column stays a
# plain uuid; the prefix is added on the way out so API responses read
# `user_02xH...` rather than a bare hex string.
type UserID = Annotated[uuid.UUID, PrefixedUUID("user")]


class UserSignup(BaseModel):
    """What the signup form sends. Email is validated, password is raw here.

    The 8-char minimum mirrors the client-side minlength on the form so the
    rule is actually enforced server-side, not just suggested in the browser.
    """

    name: str = Field(min_length=1)
    email: EmailStr
    password: str = Field(min_length=8)


class UserLogin(BaseModel):
    """Credentials posted to the login route."""

    email: EmailStr
    password: str


class PasswordResetRequest(BaseModel):
    """The 'forgot password' form: an email to send a reset link to."""

    email: EmailStr


class PasswordReset(BaseModel):
    """The reset form itself. The two password fields must agree."""

    token: str
    password: str
    confirm_password: str

    @model_validator(mode="after")
    def _passwords_match(self) -> "PasswordReset":
        if self.password != self.confirm_password:
            raise ValueError("passwords do not match")
        return self


class UserPublic(BaseModel):
    """The safe projection of a user. Never carries secret or internal fields."""

    id: UserID
    name: str
    email: EmailStr
    avatar_url: str | None
    email_verified_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserMe(UserPublic):
    """The extended self view: same safe fields plus account state."""

    provider: str | None
    is_active: bool
