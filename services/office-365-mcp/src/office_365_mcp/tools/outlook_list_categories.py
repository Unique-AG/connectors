from collections.abc import Mapping
from typing import Self

import httpx
from fastmcp import FastMCP
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.outlook_category import OutlookCategory
from msgraph.generated.users.item.outlook.master_categories.master_categories_request_builder import (  # noqa: E501
    MasterCategoriesRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_errors
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "outlook_list_categories"

STEP = "categories"

GRAPH_PERMISSIONS: tuple[str, ...] = ("MailboxSettings.Read",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

MAX_CATEGORIES = 500

_CATEGORY_FIELDS: tuple[str, ...] = ("displayName", "color")

_CategoriesQuery = MasterCategoriesRequestBuilder.MasterCategoriesRequestBuilderGetQueryParameters

_DESCRIPTION = (
    "Lists every category this mailbox can tag mail, events, and contacts with, each one's "
    "name and color."
)


class Category(BaseModel):
    name: str = Field(
        description=(
            "The category's name, exactly as it appears in a message's, event's, or contact's "
            "own `categories` list."
        )
    )
    color: str | None = Field(
        description=(
            "The preset color Outlook shows beside the category (`preset0` through `preset24`, "
            "or `none`); null when Graph reported no color."
        )
    )

    @classmethod
    def from_category(cls, category: OutlookCategory) -> Self:
        assert category.display_name is not None, (
            "Graph returned a category with no display name, which its own documentation calls "
            "the unique, unchangeable identifier of every category it lists"
        )
        return cls(
            name=category.display_name,
            color=None if category.color is None else str.__str__(category.color),
        )


class Categories(BaseModel):
    categories: list[Category] = Field(
        description=(
            "The mailbox's categories, in the order Graph returned them; empty if none are defined."
        )
    )
    capped: bool = Field(
        description=(
            f"True if the listing stopped at {MAX_CATEGORIES} categories with more remaining."
        )
    )


async def list_categories(client: GraphServiceClient) -> Categories:
    with graph_errors(TOOL_NAME, step=STEP):
        first_page = await client.me.outlook.master_categories.get(
            request_configuration=RequestConfiguration[_CategoriesQuery](
                query_parameters=_CategoriesQuery(select=list(_CATEGORY_FIELDS), top=MAX_CATEGORIES)
            )
        )
        assert first_page is not None, "Graph answered a category listing with no collection"
        collected = await collect_pages(first_page, client, limit=MAX_CATEGORIES)

    return Categories(
        categories=[Category.from_category(category) for category in collected.items],
        capped=collected.capped,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Categories",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_list_categories(client: GraphServiceClient = graph) -> Categories:
        return await list_categories(client)
