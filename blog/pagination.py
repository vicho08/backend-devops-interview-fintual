from typing import Any

from ninja import Field, Schema
from ninja.pagination import LimitOffsetPagination


class DefaultPagination(LimitOffsetPagination):
    """Limit/offset pagination with project-wide defaults.

    Accepts ?limit (default 20, max 100) and ?offset (default 0).
    Returns {"posts": [...], "count": N}.
    The Pydantic le=100 constraint rejects limit > 100 with a 422.
    """

    class Input(Schema):
        """Pagination query parameters."""

        limit: int = Field(20, ge=1, le=100)
        offset: int = Field(0, ge=0)

    class Output(Schema):
        """Paginated response envelope."""

        posts: list[Any]
        count: int

    items_attribute: str = "posts"
