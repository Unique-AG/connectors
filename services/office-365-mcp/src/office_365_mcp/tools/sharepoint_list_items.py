from collections.abc import Mapping
from typing import Annotated, Literal

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.sites.item.lists.item.items.items_request_builder import (
    ItemsRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_errors, graph_step
from office_365_mcp.shared.handles import ListHandle, list_handle
from office_365_mcp.shared.lists import (
    NOT_A_LIST_HANDLE,
    VALUE_TYPES,
    ListColumn,
    ListItemSummary,
    list_columns,
    value_refusal,
)
from office_365_mcp.shared.odata import odata_literal
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "sharepoint_list_items"

STEP_COLUMNS = "list_columns"
STEP_ITEMS = "list_items"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Sites.Read.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "list": ListHandle(
        "contoso.sharepoint.invalid,00000000-0000-4000-8000-00000000000a,"
        + "11111111-aaaa-bbbb-cccc-222222222222",
        "0b1c2d3e-0000-4000-8000-00000000000a",
    ).uri
}

Operator = Literal["eq", "ne", "lt", "gt", "le", "ge", "startswith"]

_ItemsQuery = ItemsRequestBuilder.ItemsRequestBuilderGetQueryParameters

_QUOTED_TYPES = frozenset({"text", "choice", "dateTime"})

_DESCRIPTION = """\
Reads the items of one SharePoint list, each with its column values in `fields`. Optionally \
filters on one indexed column. Call sharepoint_get_list first to learn the internal column names, \
their types, and which ones are indexed.

Notes:
- This tool does not sort the rows.
"""

_FILTER_IS_ALL_OR_NOTHING = (
    f"{TOOL_NAME} filters only when `column`, `operator`, and `value` are all given. Give all "
    + "three, or none of them to read every item."
)


class ListItems(BaseModel):
    items: list[ListItemSummary] = Field(
        description=(
            "The items, in the order Microsoft returned them. An empty list means that no item "
            + "matched."
        )
    )
    capped: bool = Field(
        description=(
            "True when `limit` or the cap of 1000 items stopped the listing while more items "
            + "remained. Raise `limit`, or filter, to see the rest. False when the listing ended "
            + "on its own."
        )
    )


async def list_items(
    client: GraphServiceClient,
    *,
    list_uri: str,
    column: str | None = None,
    operator: Operator | None = None,
    value: str | None = None,
    limit: int,
) -> ListItems:
    assert limit >= 1, f"limit must be at least 1, got {limit}"
    handle = list_handle(list_uri)
    if handle is None:
        raise ToolError(f"{TOOL_NAME} {NOT_A_LIST_HANDLE}")
    given = [argument is not None for argument in (column, operator, value)]
    if any(given) and not all(given):
        raise ToolError(_FILTER_IS_ALL_OR_NOTHING)

    with graph_errors():
        clause = None
        if column is not None and operator is not None and value is not None:
            with graph_step(STEP_COLUMNS):
                columns = await list_columns(client, handle)
            clause = _clause(columns, column, operator, value)
        with graph_step(STEP_ITEMS):
            first_page = (
                await client.sites.by_site_id(handle.site_id)
                .lists.by_list_id(handle.list_id)
                .items.get(
                    request_configuration=RequestConfiguration[_ItemsQuery](
                        query_parameters=_ItemsQuery(expand=["fields"], filter=clause)
                    )
                )
            )
            assert first_page is not None, "Graph answered an item listing with no collection"
            collected = await collect_pages(
                first_page, client, limit=limit, matches=lambda item: item.id is not None
            )

    return ListItems(
        items=[ListItemSummary.from_item(handle, item) for item in collected.items],
        capped=collected.capped,
    )


def _clause(columns: list[ListColumn], name: str, operator: Operator, value: str) -> str:
    found = next((column for column in columns if column.name == name), None)
    if found is None:
        raise ToolError(
            f"This list has no column with the internal name {name!r}. Call sharepoint_get_list "
            + "and pass the `name` of a column, not its display name."
        )
    if found.indexed is not True:
        raise ToolError(
            f"The column {name!r} is not indexed, and {TOOL_NAME} filters only on an indexed "
            + "column. Pick an indexed column from sharepoint_get_list, or read without a filter."
        )
    if operator == "startswith":
        if found.type not in {"text", "choice"}:
            raise ToolError(
                f"`startswith` works only on a text or choice column, not {found.type}."
            )
        return f"startswith(fields/{name},'{odata_literal(value)}')"
    return f"fields/{name} {operator} {_literal(found, value)}"


def _literal(column: ListColumn, value: str) -> str:
    if column.type not in VALUE_TYPES:
        raise ToolError(
            f"{TOOL_NAME} cannot filter on the column {column.name!r}, because its type is "
            + f"{column.type}. It filters on text, choice, date, number, currency, and yes or no "
            + "columns."
        )
    refusal = value_refusal(column, value)
    if refusal is not None:
        raise ToolError(refusal)
    return f"'{odata_literal(value)}'" if column.type in _QUOTED_TYPES else value


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="SharePoint: List Items",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def sharepoint_list_items(
        list: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The list to read: the `uri` of a row from sharepoint_list_lists. Copy it "
                    + "exactly."
                ),
            ),
        ],
        column: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The internal `name` of an indexed column to filter on, from "
                    + "sharepoint_get_list. Give `operator` and `value` with it."
                ),
            ),
        ] = None,
        operator: Annotated[
            Operator | None,
            Field(
                description=(
                    "How to compare `column` with `value`. `startswith` works on text and choice "
                    + "columns only."
                ),
            ),
        ] = None,
        value: Annotated[
            str | None,
            Field(
                description=(
                    "The value to compare with. Write a number as a plain decimal such as 12.5, "
                    + "a yes or no value as true or false, and a date as 2026-01-31T00:00:00Z."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                description=(
                    "How many items to return, at most. The field `capped` says if the listing "
                    + "stopped early. The default value is 25."
                ),
            ),
        ] = 25,
        client: GraphServiceClient = graph,
    ) -> ListItems:
        return await list_items(
            client, list_uri=list, column=column, operator=operator, value=value, limit=limit
        )
