import json
from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.field_value_set import FieldValueSet
from msgraph.generated.models.list_item import ListItem
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.handles import ListHandle, list_handle
from office_365_mcp.shared.lists import (
    FIELDS_RULES,
    NOT_A_LIST_HANDLE,
    FieldValue,
    ListItemSummary,
    list_columns,
    list_label,
    written_fields,
)
from office_365_mcp.shared.notes import write_state_for
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "sharepoint_create_list_item"

STEP_COLUMNS = "list_columns"
STEP_LIST = "read_list"
STEP_CREATE = "create_list_item"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Sites.ReadWrite.All",)

CHANGE_SHOWN_BY: tuple[str, ...] = ("sharepoint_list_items",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "list": ListHandle(
        "contoso.sharepoint.invalid,00000000-0000-4000-8000-00000000000a,"
        + "11111111-aaaa-bbbb-cccc-222222222222",
        "00000000-0000-4000-8000-00000000000b",
    ).uri,
    "fields": {"Title": "Synthetic task", "Status": "Open"},
}

_CREATE = "add the row"
_DO_NOT_CREATE = "do not add it"
_NOTHING_CREATED = "No row was added."

_DESCRIPTION = """\
Adds one row to a SharePoint list, given the `uri` of a list from sharepoint_list_lists and the \
values of its columns. Call sharepoint_get_list first to learn the internal column names, their \
types, and the allowed choices. sharepoint_list_items reads the new row.

Notes:
- This tool asks the user to agree before it adds anything, every time.
- It writes text, choice, date, number, currency, and yes or no columns. It refuses a call that \
names a person, lookup, managed metadata, or multi-value column, or a read-only or hidden column.
- Pass every column the user named in `fields`, even one the tool refuses, such as a person \
column. The tool refuses it before it asks the user and adds nothing, so tell the user the \
refusal. Never drop a named column or say the user did not ask for it.
- If a call times out, do not call this tool again first. Make sure that sharepoint_list_items \
does not show the row before you call again.
"""


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx, agree=_CREATE, decline=_DO_NOT_CREATE, nothing_happened=_NOTHING_CREATED
    )


async def create_list_item(
    client: GraphServiceClient, *, list_uri: str, fields: Mapping[str, str], confirm: Confirm
) -> ListItemSummary | InputRequiredResult:
    assert fields, "fields is bounded by the schema"
    handle = list_handle(list_uri)
    if handle is None:
        raise ToolError(f"{TOOL_NAME} {NOT_A_LIST_HANDLE}")
    with graph_errors(TOOL_NAME):
        outcome = await _create(client, handle, fields, confirm)
    if isinstance(outcome, str):
        raise ToolError(outcome)
    return outcome


async def _create(
    client: GraphServiceClient, handle: ListHandle, fields: Mapping[str, str], confirm: Confirm
) -> ListItemSummary | InputRequiredResult | str:
    with graph_step(STEP_COLUMNS):
        columns = await list_columns(client, handle)
    body = written_fields(columns, fields, nothing_happened=_NOTHING_CREATED)
    if isinstance(body, str):
        return body

    with graph_step(STEP_LIST):
        label = await list_label(client, handle)
    about = write_state_for(TOOL_NAME, handle.uri, label, json.dumps(dict(fields), sort_keys=True))
    with not_graph():
        answer = await confirm(_question(label, body), about)
    if answer is not None:
        return answer

    with graph_step(STEP_CREATE):
        created = await (
            client.sites.by_site_id(handle.site_id)
            .lists.by_list_id(handle.list_id)
            .items.post(
                ListItem(fields=FieldValueSet(additional_data=dict(body))),
                request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
            )
        )
    assert created is not None, "Graph answered a list item create with no item"
    return ListItemSummary.from_item(handle, created)


def _question(label: str, body: Mapping[str, FieldValue]) -> str:
    shown = "; ".join(f"{name}: {cut_for_a_question(str(value))!r}" for name, value in body.items())
    return f"Add a row to the SharePoint list {label} with {shown}?"


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Create a List Item",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def sharepoint_create_list_item(
        list: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The list that gets the row: the `uri` of a row from sharepoint_list_lists. "
                    + "Copy it exactly."
                ),
            ),
        ],
        fields: Annotated[
            dict[str, str],
            Field(min_length=1, description=f"The values of the new row. {FIELDS_RULES}"),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> ListItemSummary | InputRequiredResult:
        return await create_list_item(
            client, list_uri=list, fields=fields, confirm=a_person_agrees(ctx)
        )
