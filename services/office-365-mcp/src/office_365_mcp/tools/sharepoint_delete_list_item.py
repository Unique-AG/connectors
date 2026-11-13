from collections.abc import Mapping
from contextlib import suppress
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.sites.item.lists.item.items.item.list_item_item_request_builder import (
    ListItemItemRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphNotFound, graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.handles import ListHandle, ListItemHandle, list_item_handle
from office_365_mcp.shared.lists import list_label
from office_365_mcp.shared.notes import write_state_for
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "sharepoint_delete_list_item"

STEP_LIST = "read_list"
STEP_READ_ITEM = "list_item"
STEP_DELETE = "delete_list_item"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Sites.ReadWrite.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "item": ListItemHandle(
        "contoso.sharepoint.invalid,00000000-0000-4000-8000-00000000000a,"
        + "11111111-aaaa-bbbb-cccc-222222222222",
        "00000000-0000-4000-8000-00000000000b",
        "7",
    ).uri,
}

_DELETE = "delete the row"
_KEEP_THE_ROW = "keep the row"
_NOTHING_DELETED = "The row was not moved to the recycle bin."

_ItemQuery = ListItemItemRequestBuilder.ListItemItemRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Moves one row of a SharePoint list to the recycle bin of its site, given the `uri` of an item \
from sharepoint_list_items. This connector never erases a row permanently.

Notes:
- This tool asks the user to agree before it changes anything, every time, and names the row.
- This call is safe to repeat after a timeout. A second call finds no row and reports that.
"""

_NOT_AN_ITEM_HANDLE = (
    f"{_NOTHING_DELETED} {TOOL_NAME} takes a list item handle: the `uri` of a row from "
    + "sharepoint_list_items, copied exactly. A list handle, an item title, an item id, and a web "
    + "address are not item handles. If you call this tool again with the same arguments, the "
    + "call will fail the same way."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 has no such row to delete, and this call deleted nothing. The row is probably "
    + "already gone. Read the list again with sharepoint_list_items. If the row is not there, "
    + "nothing is left to delete. The same handle fails the same way, so do not retry it."
)


class DeletedListItem(BaseModel):
    title: str | None = Field(
        description="The Title of the row before the delete. Null when the row had no Title."
    )
    list_uri: str = Field(
        description=(
            "The handle of the list that held the row. Pass it to sharepoint_list_items to see "
            + "what is left in the list."
        )
    )
    deleted: Literal[True] = Field(
        description=(
            "Always true, because this tool answers only when the row is gone. It is also true "
            + "when Graph found no row to delete after this tool read it."
        )
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx, agree=_DELETE, decline=_KEEP_THE_ROW, nothing_happened=_NOTHING_DELETED
    )


async def delete_list_item(
    client: GraphServiceClient, *, item_uri: str, confirm: Confirm
) -> DeletedListItem | InputRequiredResult:
    handle = list_item_handle(item_uri)
    if handle is None:
        raise ToolError(_NOT_AN_ITEM_HANDLE)
    item = (
        client.sites.by_site_id(handle.site_id)
        .lists.by_list_id(handle.list_id)
        .items.by_list_item_id(handle.item_id)
    )
    with graph_errors():
        with graph_step(STEP_READ_ITEM):
            current = await item.get(
                request_configuration=RequestConfiguration[_ItemQuery](
                    query_parameters=_ItemQuery(expand=["fields"])
                )
            )
        assert current is not None, "Graph answered a list item read with no item"
        fields = {} if current.fields is None else current.fields.additional_data
        title = fields.get("Title")
        title = title if isinstance(title, str) and title else None

        with graph_step(STEP_LIST):
            label = await list_label(client, ListHandle(handle.site_id, handle.list_id))
        with not_graph():
            answer = await confirm(
                _question(label, title, handle),
                write_state_for(TOOL_NAME, handle.uri, label, title or ""),
            )
        if answer is None:
            with suppress(GraphNotFound), graph_step(STEP_DELETE):
                await item.delete(
                    request_configuration=RequestConfiguration[QueryParameters](options=no_retry())
                )

    if isinstance(answer, str):
        raise ToolError(answer)
    if answer is not None:
        return answer
    return DeletedListItem(
        title=title, list_uri=ListHandle(handle.site_id, handle.list_id).uri, deleted=True
    )


def _question(label: str, title: str | None, handle: ListItemHandle) -> str:
    row = f"with id {handle.item_id}" if title is None else repr(cut_for_a_question(title))
    return f"Move the row {row} of the SharePoint list {label} to the recycle bin of its site?"


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="SharePoint: Delete a List Item",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def sharepoint_delete_list_item(
        item: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The row to move to the recycle bin: the `uri` of an item from "
                    + "sharepoint_list_items. Copy it exactly."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> DeletedListItem | InputRequiredResult:
        return await delete_list_item(client, item_uri=item, confirm=a_person_agrees(ctx))
