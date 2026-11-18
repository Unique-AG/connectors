from collections.abc import Mapping
from typing import Annotated

from fastmcp.exceptions import ToolError
from pydantic import Field
from pydantic import ValidationError

from polixis_mcp import contexts

Cursor = Annotated[
    str | None,
    Field(
        description=(
            "The `next_cursor` of the previous page, to get the next one. Pass it alone: it "
            "carries every argument of the first call, and the others are ignored."
        )
    ),
]

PageSize = Annotated[
    int | None,
    Field(
        ge=1,
        le=100,
        description=(
            "At most this many rows on a page. Leave it out: a page then holds as many of the "
            "ranked rows as fit in about 8,000 tokens."
        ),
    ),
]


def page_query[Q: contexts.PageQuery](
    query_type: type[Q],
    cursor: str | None,
    *,
    fixed: Mapping[str, object] | None = None,
    **arguments: object,
) -> Q:
    """The query a cursor carries, or else the one the arguments make. `fixed` holds what the
    tool sets itself, so a cursor of another tool sharing the query type fails as well. A
    ToolError names the arguments that are missing or invalid.
    """
    fixed = fixed or {}
    if cursor:
        try:
            return contexts.decode_cursor(cursor, query_type, fixed=fixed)
        except contexts.InvalidCursorError as error:
            raise ToolError(str(error)) from error
    try:
        return query_type.model_validate(
            {**{name: value for name, value in arguments.items() if value is not None}, **fixed}
        )
    except ValidationError as error:
        invalid = sorted({str(detail["loc"][0]) for detail in error.errors() if detail["loc"]})
        raise ToolError(
            f"Missing or invalid: {', '.join(invalid)}. Pass them, or the `cursor` of a page."
        ) from error
