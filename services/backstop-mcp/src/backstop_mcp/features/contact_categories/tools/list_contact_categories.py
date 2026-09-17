from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.contact_categories import (
    ListContactCategoriesQuery,
    ListContactCategoriesResponse,
    get_list_contact_categories_query_factory,
)
from backstop_mcp.models import published_output_schema


@tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(ListContactCategoriesResponse),
)
async def list_contact_categories(
    search: Annotated[
        str | None,
        Field(
            description=(
                "Optional case-insensitive substring of the category name. The argument is "
                "`search`. Filters the walk in memory — the query never sends "
                "`filter[name][like]`."
            ),
        ),
    ] = None,
    refresh: Annotated[
        bool,
        Field(description="Do not pass true unless the user reports a missing category."),
    ] = False,
    list_contact_categories_query: ListContactCategoriesQuery = Depends(
        get_list_contact_categories_query_factory
    ),
) -> ListContactCategoriesResponse:
    """List the standard Backstop contact-category vocabulary.

    Use when you need a category id for create_person, update_person,
    create_organization, or update_organization (`category_ids`, `add_category_ids`,
    `replace_category_ids`). These are first-class CRM values, not custom fields — do
    not look them up on list_custom_fields. Pass `search` to keep categories whose name
    contains that substring. Pass refresh=true only when the user reports a missing category.

    Call like: {"search": "key"}
    """
    return await list_contact_categories_query.run(search=search, refresh=refresh)
