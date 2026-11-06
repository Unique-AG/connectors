import json
from collections.abc import Mapping

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.shared.handles import ListItemHandle
from office_365_mcp.shared.lists import ListItemSummary
from office_365_mcp.shared.seam import Confirm
from office_365_mcp.tools.sharepoint_update_list_item import update_list_item

_SITE_ID = (
    "contoso.sharepoint.invalid,00000000-0000-4000-8000-00000000000a,"
    + "11111111-aaaa-bbbb-cccc-222222222222"
)
_LIST_ID = "00000000-0000-4000-8000-00000000000b"
_ITEM_URI = ListItemHandle(_SITE_ID, _LIST_ID, "7").uri
_COLUMNS_ROUTE = f"/sites/{_SITE_ID}/lists/{_LIST_ID}/columns"
_ITEM_ROUTE = f"/sites/{_SITE_ID}/lists/{_LIST_ID}/items/7"
_FIELDS_ROUTE = f"{_ITEM_ROUTE}/fields"
_ETAG = '"00000000-0000-4000-8000-00000000000c,3"'

_COLUMNS: list[dict[str, object]] = [
    {"name": "Title", "displayName": "Title", "text": {}},
    {"name": "Status", "displayName": "Status", "choice": {"choices": ["Open", "Closed"]}},
    {"name": "Tags", "displayName": "Tags", "choice": {"choices": ["a", "b"]}},
    {"name": "Owner", "displayName": "Owner", "personOrGroup": {}},
    {"name": "Parent", "displayName": "Parent", "lookup": {}},
    {"name": "Topic", "displayName": "Topic", "term": {}},
]


def _item(*, etag: str | None = _ETAG) -> dict[str, object]:
    item: dict[str, object] = {
        "id": "7",
        "webUrl": "https://contoso.sharepoint.invalid/sites/Finance/Lists/Tasks/7_.000",
        "fields": {"id": "7", "Title": "Close books", "Status": "Open", "Tags": ["a"]},
    }
    if etag is not None:
        item["eTag"] = etag
    return item


def _reads(graph: respx.MockRouter, item: Mapping[str, object] | None = None) -> None:
    _ = graph.get(_COLUMNS_ROUTE).mock(return_value=httpx.Response(200, json={"value": _COLUMNS}))
    _ = graph.get(_ITEM_ROUTE).mock(
        return_value=httpx.Response(200, json=dict(_item() if item is None else item))
    )


def _patches(graph: respx.MockRouter, response: httpx.Response | None = None) -> respx.Route:
    answer = response or httpx.Response(
        200, json={"id": "7", "Title": "Close books", "Status": "Closed"}
    )
    return graph.patch(_FIELDS_ROUTE).mock(return_value=answer)


async def _agrees(question: str, about: str) -> str | None:
    assert question
    assert about
    return None


async def _declines(question: str, about: str) -> str | None:
    assert question
    assert about
    return "Nothing was changed."


def _asking(asked: list[str]) -> Confirm:
    async def recording(question: str, about: str) -> str | None:
        assert about
        asked.append(question)
        return None

    return recording


async def _update(
    client: GraphServiceClient, fields: Mapping[str, str], confirm: Confirm = _agrees
) -> ListItemSummary:
    updated = await update_list_item(client, item_uri=_ITEM_URI, fields=fields, confirm=confirm)
    assert isinstance(updated, ListItemSummary), "this call was answered with a question"
    return updated


async def test_it_patches_with_the_item_etag_and_shows_old_and_new_values(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    _reads(graph)
    patch = _patches(graph)
    asked: list[str] = []

    updated = await _update(client, {"Status": "Closed"}, _asking(asked))

    assert patch.call_count == 1
    request = patch.calls.last.request
    assert request.headers["If-Match"] == _ETAG
    assert json.loads(request.content) == {"Status": "Closed"}
    (question,) = asked
    assert "Status: 'Open' to 'Closed'" in question
    assert updated.uri == _ITEM_URI
    assert updated.fields["Status"] == "Closed"


async def test_a_declined_question_sends_nothing(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    _reads(graph)
    patch = _patches(graph)

    with pytest.raises(ToolError, match="Nothing was changed."):
        _ = await update_list_item(
            client, item_uri=_ITEM_URI, fields={"Status": "Closed"}, confirm=_declines
        )

    assert not patch.called


async def test_a_changed_row_is_a_tool_error_that_sends_the_model_to_read_again(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    _reads(graph)
    patch = _patches(
        graph,
        httpx.Response(412, json={"error": {"code": "resourceModified", "message": "changed"}}),
    )

    with pytest.raises(ToolError, match="sharepoint_list_items"):
        _ = await _update(client, {"Status": "Closed"})

    assert patch.call_count == 1


async def test_an_item_without_an_etag_is_refused_before_the_patch(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    _reads(graph, _item(etag=None))
    patch = _patches(graph)
    asked: list[str] = []

    with pytest.raises(ToolError):
        _ = await _update(client, {"Status": "Closed"}, _asking(asked))

    assert not patch.called
    assert asked == []


@pytest.mark.parametrize(
    "fields",
    [
        {"Owner": "someone@contoso.sharepoint.invalid"},
        {"OwnerLookupId": "7"},
        {"Parent": "3"},
        {"Topic": "Finance"},
        {"Tags": "b"},
        {"Status": "Pending"},
        {"Missing": "x"},
    ],
)
async def test_a_column_it_cannot_write_sends_nothing_and_asks_nobody(
    client: GraphServiceClient, graph: respx.MockRouter, fields: Mapping[str, str]
) -> None:
    _reads(graph)
    patch = _patches(graph)
    asked: list[str] = []

    with pytest.raises(ToolError):
        _ = await _update(client, fields, _asking(asked))

    assert not patch.called
    assert asked == []


@pytest.mark.parametrize("value", ["Tasks", ListItemHandle(_SITE_ID, _LIST_ID, "7").uri[:-2]])
async def test_a_value_that_is_not_an_item_handle_makes_no_graph_call(
    client: GraphServiceClient, graph: respx.MockRouter, value: str
) -> None:
    with pytest.raises(ToolError):
        _ = await update_list_item(
            client, item_uri=value, fields={"Status": "Closed"}, confirm=_agrees
        )

    assert not graph.calls
