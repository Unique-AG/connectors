"""`outlook_list_categories` — the master category list this mailbox tags mail, events and
contacts with: every name Outlook offers, paired with the color shown beside it.

- `name` is what a caller writes back to assign a category. This tool does not report an id;
  Microsoft documents `displayName` itself as the unique, unchangeable key.
- TRAP: `color` deserializes to `CategoryColor`, an enum kiota mixes `str` into without making it
  a `StrEnum`. Its inherited `__str__` answers `CategoryColor.Preset3`, not `preset3`.
  `str.__str__(color)` reads the value Microsoft actually sent.

**This tool takes no `mailbox` argument.** Microsoft publishes no `.Shared` variant of
`MailboxSettings.Read`, for the same reason `outlook_get_mailbox_settings` takes none.
"""

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

_DESCRIPTION = """\
Lists every category the signed-in user's mailbox can tag mail, events and contacts with — each \
one's name and the color Outlook shows beside it. outlook_get_mailbox_settings also reports \
category names, as one line of a wider mailbox report; this tool is the dedicated listing, with \
color included.

Notes:
- A message's, event's or contact's own `categories` field holds these categories by name — \
write and match on `name`, verbatim, never on an id.
- `color` is one of Microsoft's fixed presets (`preset0` through `preset24`, or the literal \
string `none`), the same palette Outlook itself offers when a category is created. It is never \
a hex code.
"""


class Category(BaseModel):
    """One category this mailbox has defined, as Outlook itself shows it: a name and the color
    beside it. The name is the identifying value — Microsoft documents it as unique per mailbox
    and unchangeable once created — so nothing else here addresses a category more precisely."""

    name: str = Field(
        description=(
            "The category's name, chosen by whoever created it. This is the exact string a "
            + "message's, event's or contact's own `categories` list holds — write and match on "
            + "this, never on an id, which this tool does not report because nothing else in "
            + "this connector reads one."
        )
    )
    color: str | None = Field(
        description=(
            "The preset color Outlook shows beside this category, in Microsoft's own spelling — "
            + "`preset0` through `preset24`, or the literal string `none` for a category nobody "
            + "assigned a color to. This is a fixed palette id, never a hex code. This field is "
            + "null only when Graph reported no color property at all, which is a different, "
            + "rarer answer than the explicit `none` above."
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
    """Every category this mailbox has defined, in the order Graph returned them."""

    categories: list[Category] = Field(
        description=(
            "The mailbox's categories, in the order Graph returned them — not alphabetical and "
            + "not grouped by color. Empty means the mailbox has defined none, which is the "
            + "state of a mailbox where nobody in Outlook has created or renamed one yet."
        )
    )
    capped: bool = Field(
        description=(
            f"True means the listing stopped at {MAX_CATEGORIES} categories, with more still on "
            + "offer, so `categories` is missing some. False means every category the mailbox "
            + "holds was read, however few or many that is."
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
