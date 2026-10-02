from collections.abc import Mapping
from typing import Annotated, Literal

import httpx
from fastmcp import FastMCP
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from msgraph.generated.models.category_color import CategoryColor
from msgraph.generated.models.outlook_category import OutlookCategory
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, no_retry
from office_365_mcp.shared.categories import CategoryName
from office_365_mcp.shared.odata import spelled
from office_365_mcp.shared.seam import WRITE_ADDITIVE, graph_client_for_caller

TOOL_NAME = "outlook_create_category"

STEP_CREATE_CATEGORY = "create_category"

GRAPH_PERMISSIONS: tuple[str, ...] = ("MailboxSettings.ReadWrite",)

CHANGE_SHOWN_BY: tuple[str, ...] = ("outlook_list_categories",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"name": "Synthetic category"}

type CategoryColorName = Literal[
    "none",
    "preset0",
    "preset1",
    "preset2",
    "preset3",
    "preset4",
    "preset5",
    "preset6",
    "preset7",
    "preset8",
    "preset9",
    "preset10",
    "preset11",
    "preset12",
    "preset13",
    "preset14",
    "preset15",
    "preset16",
    "preset17",
    "preset18",
    "preset19",
    "preset20",
    "preset21",
    "preset22",
    "preset23",
    "preset24",
]

_DESCRIPTION = """\
Creates one new category, with a name and a color, in the signed-in user's own list of \
categories. There is no draft and no review step. The list belongs to the user's own mailbox \
alone, so this tool never asks anybody to agree. A new category is on no message at first. \
If this deployment exposes outlook_mark_mail, that tool puts a category on a message.

Notes:
- Each category name is unique in the list. Microsoft refuses a name that the list already has. \
If you call this tool again with the same arguments, the call will fail the same way.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
outlook_list_categories does not show a category named `name`.
"""


class CreatedCategory(BaseModel):
    name: str = Field(
        description=(
            "The category's name, as Microsoft stored it. A message or event carries this exact "
            "name in its own `categories` list."
        )
    )
    color: str | None = Field(
        description=(
            "The preset color Microsoft stored (`preset0` through `preset24`, or `none`). Null "
            "when Graph reported no color."
        )
    )


async def create_category(
    client: GraphServiceClient, *, name: str, color: CategoryColorName
) -> CreatedCategory:
    with graph_errors(TOOL_NAME, step=STEP_CREATE_CATEGORY):
        created = await client.me.outlook.master_categories.post(
            OutlookCategory(display_name=name, color=CategoryColor(color)),
            request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
        )
    assert created is not None, "Graph answered a category create with no category"
    return _answer(created)


def _answer(category: OutlookCategory) -> CreatedCategory:
    assert category.display_name is not None, (
        "Graph created a category with no display name, which is the only name a category has"
    )
    return CreatedCategory(name=category.display_name, color=spelled(category.color))


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Create a Category",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def outlook_create_category(
        name: Annotated[
            CategoryName,
            Field(
                description=(
                    "The new category's name, as the user writes it. The name must be unique in "
                    "the user's list of categories and cannot change after this call. The "
                    "answer's `name` is what Microsoft stored."
                ),
            ),
        ],
        color: Annotated[
            CategoryColorName,
            Field(
                description=(
                    "The category's color as Outlook desktop shows it. `none` shows no color. "
                    "preset0 to preset9 are red, orange, brown, yellow, green, teal, olive, blue, "
                    "purple, cranberry. preset10 to preset14 are steel, dark steel, gray, dark "
                    "gray, black. preset15 to preset24 are the dark forms of preset0 to preset9."
                ),
            ),
        ] = "none",
        client: GraphServiceClient = graph,
    ) -> CreatedCategory:
        return await create_category(client, name=name, color=color)
