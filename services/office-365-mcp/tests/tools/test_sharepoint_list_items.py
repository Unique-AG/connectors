from collections.abc import Mapping

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.shared.handles import ListHandle, ListItemHandle, list_item_handle
from office_365_mcp.tools.sharepoint_list_items import list_items

_SITE_ID = (
    "contoso.sharepoint.invalid,00000000-0000-4000-8000-00000000000a,"
    + "11111111-aaaa-bbbb-cccc-222222222222"
)
_LIST_ID = "0b1c2d3e-0000-4000-8000-00000000000a"
_LIST_URI = ListHandle(_SITE_ID, _LIST_ID).uri
_COLUMNS_ROUTE = f"/sites/{_SITE_ID}/lists/{_LIST_ID}/columns"
_ITEMS_ROUTE = f"/sites/{_SITE_ID}/lists/{_LIST_ID}/items"


def _column(name: str, facet: str, *, indexed: bool | None) -> dict[str, object]:
    column: dict[str, object] = {"name": name, "displayName": name, facet: {}}
    if indexed is not None:
        column["indexed"] = indexed
    return column


_COLUMNS = [
    _column("Title", "text", indexed=True),
    _column("Status", "choice", indexed=True),
    _column("Amount", "number", indexed=True),
    _column("Done", "boolean", indexed=True),
    _column("Owner", "personOrGroup", indexed=True),
    _column("Notes", "text", indexed=False),
    _column("Region", "text", indexed=None),
]

_ITEM = {
    "id": "7",
    "webUrl": "https://contoso.sharepoint.invalid/sites/Finance/Lists/Tasks/7_.000",
    "lastModifiedDateTime": "2026-02-11T09:15:22Z",
    "fields": {"id": "70", "Title": "Close books", "Amount": 12.5, "CustomTag": "q1"},
}


def _columns(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_COLUMNS_ROUTE).mock(
        return_value=httpx.Response(200, json={"value": _COLUMNS})
    )


def _items(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_ITEMS_ROUTE).mock(return_value=httpx.Response(200, json={"value": [_ITEM]}))


def _query(route: respx.Route) -> Mapping[str, str]:
    request: httpx.Request = route.calls.last.request
    return dict(request.url.params)


async def test_it_returns_items_with_their_fields_and_a_handle(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    items = _items(graph)

    result = await list_items(client, list_uri=_LIST_URI, limit=25)

    (row,) = result.items
    assert list_item_handle(row.uri) == ListItemHandle(_SITE_ID, _LIST_ID, "7")
    assert row.fields == {"id": "70", "Title": "Close books", "Amount": 12.5, "CustomTag": "q1"}
    assert (
        row.web_url
        == "https://contoso.sharepoint.invalid/sites/Finance/Lists/Tasks/DispForm.aspx?ID=7"
    )
    assert row.last_modified_at is not None
    assert row.last_modified_at.isoformat() == "2026-02-11T09:15:22+00:00"
    assert result.capped is False
    assert _query(items) == {"$expand": "fields"}


async def test_an_indexed_eq_filter_is_the_only_items_query(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    columns = _columns(graph)
    items = _items(graph)

    _ = await list_items(
        client, list_uri=_LIST_URI, column="Status", operator="eq", value="Open", limit=25
    )

    assert columns.call_count == 1
    assert items.call_count == 1
    assert _query(items) == {"$expand": "fields", "$filter": "fields/Status eq 'Open'"}


@pytest.mark.parametrize(
    ("column", "operator", "value", "clause"),
    [
        ("Title", "startswith", "O'Neil", "startswith(fields/Title,'O''Neil')"),
        ("Amount", "ge", "-12.50", "fields/Amount ge -12.50"),
        ("Done", "ne", "true", "fields/Done ne true"),
    ],
)
async def test_it_spells_the_literal_for_the_column_type(
    client: GraphServiceClient,
    graph: respx.MockRouter,
    column: str,
    operator: str,
    value: str,
    clause: str,
) -> None:
    _ = _columns(graph)
    items = _items(graph)

    _ = await list_items(
        client,
        list_uri=_LIST_URI,
        column=column,
        operator=operator,  # pyright: ignore[reportArgumentType]
        value=value,
        limit=25,
    )

    assert _query(items)["$filter"] == clause


@pytest.mark.parametrize(
    ("column", "operator", "value"),
    [
        ("Notes", "eq", "x"),
        ("Region", "eq", "x"),
        ("Missing", "eq", "x"),
        ("Owner", "eq", "Ada"),
        ("Amount", "eq", "12 or 1 eq 1"),
        ("Done", "eq", "yes"),
        ("Amount", "startswith", "1"),
    ],
)
async def test_a_filter_it_cannot_send_never_reaches_the_items_route(
    client: GraphServiceClient, graph: respx.MockRouter, column: str, operator: str, value: str
) -> None:
    _ = _columns(graph)
    items = _items(graph)

    with pytest.raises(ToolError):
        _ = await list_items(
            client,
            list_uri=_LIST_URI,
            column=column,
            operator=operator,  # pyright: ignore[reportArgumentType]
            value=value,
            limit=25,
        )

    assert not items.called


@pytest.mark.parametrize(
    ("list_uri", "column", "operator", "value"),
    [
        (_LIST_URI, "Status", None, None),
        (_LIST_URI, None, "eq", "Open"),
        (_LIST_URI, "Status", "eq", None),
        ("Tasks", None, None, None),
    ],
)
async def test_bad_arguments_make_no_graph_call(
    client: GraphServiceClient,
    graph: respx.MockRouter,
    list_uri: str,
    column: str | None,
    operator: str | None,
    value: str | None,
) -> None:
    with pytest.raises(ToolError):
        _ = await list_items(
            client,
            list_uri=list_uri,
            column=column,
            operator=operator,  # pyright: ignore[reportArgumentType]
            value=value,
            limit=25,
        )

    assert not graph.calls
