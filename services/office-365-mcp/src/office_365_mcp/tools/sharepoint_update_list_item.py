import json
from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from kiota_abstractions.headers_collection import HeadersCollection
from mcp.types import InputRequiredResult
from msgraph.generated.models.field_value_set import FieldValueSet
from msgraph.generated.models.list_item import ListItem
from msgraph.generated.sites.item.lists.item.items.item.list_item_item_request_builder import (
    ListItemItemRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import GraphFailure, graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.handles import ListHandle, ListItemHandle, list_item_handle
from office_365_mcp.shared.lists import (
    FIELDS_RULES,
    FieldValue,
    ListItemSummary,
    list_columns,
    written_fields,
)
from office_365_mcp.shared.notes import write_state_for
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Advised,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "sharepoint_update_list_item"

STEP_COLUMNS = "list_columns"
STEP_READ_ITEM = "list_item"
STEP_UPDATE = "update_list_item"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Sites.ReadWrite.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "item": ListItemHandle(
        "contoso.sharepoint.invalid,00000000-0000-4000-8000-00000000000a,"
        + "11111111-aaaa-bbbb-cccc-222222222222",
        "00000000-0000-4000-8000-00000000000b",
        "7",
    ).uri,
    "fields": {"Status": "Closed"},
}

_PRECONDITION_FAILED = 412

_UPDATE = "change the row"
_DO_NOT_UPDATE = "do not change it"
_NOTHING_CHANGED = "Nothing was changed."
_EMPTY = "(empty)"

_ItemQuery = ListItemItemRequestBuilder.ListItemItemRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Changes columns of one row of a SharePoint list, given the `uri` of an item from \
sharepoint_list_items. It changes only the columns named in `fields` and keeps the others. Call \
sharepoint_get_list first to learn the internal column names, their types, and the allowed choices.

Notes:
- This tool asks the user to agree before it changes anything, every time, and shows the old and \
the new value of each column.
- It writes text, choice, date, number, currency, and yes or no columns. It refuses a person, \
lookup, managed metadata, or multi-value column, and a read-only or hidden column.
- If somebody changes the row between this tool's read and its write, Microsoft refuses and \
nothing changes.
- This call is safe to repeat after a timeout.
"""

_NOT_AN_ITEM_HANDLE = (
    f"{_NOTHING_CHANGED} {TOOL_NAME} takes a list item handle: the `uri` of a row from "
    + "sharepoint_list_items, copied exactly. A list handle, an item title, an item id, and a web "
    + "address are not item handles. If you call this tool again with the same arguments, the "
    + "call will fail the same way."
)

_NO_ETAG = (
    f"{_NOTHING_CHANGED} Microsoft 365 sent this row without a version tag, so this connector "
    + "cannot make sure that nobody changed it in the meantime. Tell the user to change the row "
    + "in SharePoint."
)

_CHANGED_SINCE_READ = (
    f"{_NOTHING_CHANGED} Somebody changed this row after this tool read it, so Microsoft 365 "
    + "refused the write. Read the row again with sharepoint_list_items, show the user its "
    + "current values, and ask them again before you call this tool."
)


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx, agree=_UPDATE, decline=_DO_NOT_UPDATE, nothing_happened=_NOTHING_CHANGED
    )


async def update_list_item(
    client: GraphServiceClient, *, item_uri: str, fields: Mapping[str, str], confirm: Confirm
) -> ListItemSummary | InputRequiredResult:
    assert fields, "fields is bounded by the schema"
    handle = list_item_handle(item_uri)
    if handle is None:
        raise ToolError(_NOT_AN_ITEM_HANDLE)
    try:
        with graph_errors(TOOL_NAME):
            outcome = await _update(client, handle, fields, confirm)
    except GraphFailure as failure:
        if failure.status != _PRECONDITION_FAILED:
            raise
        raise Advised(_CHANGED_SINCE_READ) from failure
    if isinstance(outcome, str):
        raise ToolError(outcome)
    return outcome


async def _update(
    client: GraphServiceClient, handle: ListItemHandle, fields: Mapping[str, str], confirm: Confirm
) -> ListItemSummary | InputRequiredResult | str:
    owner = ListHandle(handle.site_id, handle.list_id)
    item = (
        client.sites.by_site_id(handle.site_id)
        .lists.by_list_id(handle.list_id)
        .items.by_list_item_id(handle.item_id)
    )
    with graph_step(STEP_COLUMNS):
        columns = await list_columns(client, owner)
    with graph_step(STEP_READ_ITEM):
        current = await item.get(
            request_configuration=RequestConfiguration[_ItemQuery](
                query_parameters=_ItemQuery(expand=["fields"])
            )
        )
    assert current is not None, "Graph answered a list item read with no item"
    old = {} if current.fields is None else current.fields.additional_data

    body = written_fields(columns, fields, nothing_happened=_NOTHING_CHANGED)
    if isinstance(body, str):
        return body
    multi = next((name for name in body if isinstance(old.get(name), list)), None)
    if multi is not None:
        return (
            f"{_NOTHING_CHANGED} The column {multi!r} holds several values, and this connector "
            + "does not write a multi-value column. Tell the user to change it in SharePoint."
        )
    if current.e_tag is None:
        return _NO_ETAG

    about = write_state_for(
        TOOL_NAME, handle.uri, current.e_tag, json.dumps(dict(fields), sort_keys=True)
    )
    with not_graph():
        answer = await confirm(_question(body, old), about)
    if answer is not None:
        return answer

    headers = HeadersCollection()
    headers.add("If-Match", current.e_tag)
    with graph_step(STEP_UPDATE):
        patched = await item.fields.patch(
            FieldValueSet(additional_data=dict(body)),
            request_configuration=RequestConfiguration[QueryParameters](
                headers=headers, options=no_retry()
            ),
        )
    assert patched is not None, "Graph answered a list item update with no fields"
    return ListItemSummary.from_item(
        owner, ListItem(id=handle.item_id, web_url=current.web_url, fields=patched)
    )


def _question(body: Mapping[str, FieldValue], old: Mapping[str, object]) -> str:
    changes = "; ".join(
        f"{name}: {_shown(old.get(name))} to {_shown(value)}" for name, value in body.items()
    )
    return f"Change this SharePoint list row? {changes}."


def _shown(value: object) -> str:
    return _EMPTY if value is None else repr(cut_for_a_question(str(value)))


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Update a List Item",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def sharepoint_update_list_item(
        item: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The row to change: the `uri` of an item from sharepoint_list_items. Copy it "
                    + "exactly."
                ),
            ),
        ],
        fields: Annotated[
            dict[str, str],
            Field(min_length=1, description=f"The new values of the columns. {FIELDS_RULES}"),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> ListItemSummary | InputRequiredResult:
        return await update_list_item(
            client, item_uri=item, fields=fields, confirm=a_person_agrees(ctx)
        )
