"""Pagination math: a pure function over a list, no I/O."""

from app.schemas.common import PaginatedResponse
from app.utils.pagination import paginate


def test_basic_window() -> None:
    result = paginate(list(range(25)), page=2, per_page=10)

    assert isinstance(result, PaginatedResponse)
    assert result.items == list(range(10, 20))
    assert result.page == 2
    assert result.per_page == 10
    assert result.total == 25
    assert result.pages == 3


def test_last_page_is_partial() -> None:
    result = paginate(list(range(25)), page=3, per_page=10)

    assert result.items == [20, 21, 22, 23, 24]
    assert result.pages == 3


def test_page_below_one_clamps_to_first() -> None:
    result = paginate(list(range(5)), page=0, per_page=10)

    assert result.page == 1
    assert result.items == list(range(5))


def test_page_past_end_clamps_to_last() -> None:
    result = paginate(list(range(25)), page=99, per_page=10)

    assert result.page == 3
    assert result.items == [20, 21, 22, 23, 24]


def test_empty_is_one_empty_page() -> None:
    result = paginate([], page=1, per_page=10)

    assert result.items == []
    assert result.total == 0
    assert result.pages == 1
    assert result.page == 1


def test_exact_multiple_does_not_add_trailing_page() -> None:
    result = paginate(list(range(20)), page=1, per_page=10)

    assert result.pages == 2
