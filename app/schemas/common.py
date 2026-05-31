from pydantic import BaseModel


class MessageResponse(BaseModel):
    """A simple human-readable result, used for confirmations and notices."""

    message: str


class ErrorResponse(BaseModel):
    """A structured error body returned by the JSON API surface."""

    detail: str


class PaginatedResponse[T](BaseModel):
    """A page of results plus the cursors a client needs to walk the rest."""

    items: list[T]
    page: int
    per_page: int
    total: int
    pages: int
