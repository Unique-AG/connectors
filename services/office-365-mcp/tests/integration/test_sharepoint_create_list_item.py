import json
from collections.abc import Mapping
from typing import cast

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphUnavailable
from office_365_mcp.shared.handles import ListHandle, ListItemHandle, list_item_handle
from office_365_mcp.shared.lists import ListItemSummary
from office_365_mcp.shared.seam import Confirm
from office_365_mcp.tools.sharepoint_create_list_item import a_person_agrees, create_list_item
from tests.integration.two_call_confirmation import accepted, modern_context

_SITE_ID = (
    "contoso.sharepoint.invalid,00000000-0000-4000-8000-00000000000a,"
    + "11111111-aaaa-bbbb-cccc-222222222222"
)
_LIST_ID = "00000000-0000-4000-8000-00000000000b"
_LIST_URI = ListHandle(_SITE_ID, _LIST_ID).uri
_COLUMNS_ROUTE = f"/sites/{_SITE_ID}/lists/{_LIST_ID}/columns"
_LIST_ROUTE = f"/sites/{_SITE_ID}/lists/{_LIST_ID}"
_LIST_URL = "https://contoso.sharepoint.invalid/sites/Finance/Lists/Tasks"
_ITEMS_ROUTE = f"/sites/{_SITE_ID}/lists/{_LIST_ID}/items"


def _column(name: str, facet: str, **extra: object) -> dict[str, object]:
    return {"name": name, "displayName": name, facet: {}, **extra}


_COLUMNS = [
    _column("Title", "text"),
    {"name": "Status", "displayName": "Status", "choice": {"choices": ["Open", "Closed"]}},
    _column("Amount", "number"),
    _column("Done", "boolean"),
    _column("Due", "dateTime"),
    _column("Owner", "personOrGroup"),
    {
        "name": "Tags",
        "displayName": "Tags",
        "choice": {"choices": ["a", "b"], "displayAs": "checkBoxes"},
    },
    _column("Parent", "lookup"),
    _column("Topic", "term"),
    _column("Location", "geolocation"),
    _column("Created", "dateTime", readOnly=True),
    _column("Secret", "text", hidden=True),
]

_CREATED = {
    "id": "8",
    "webUrl": "https://contoso.sharepoint.invalid/sites/Finance/Lists/Tasks/8_.000",
    "lastModifiedDateTime": "2026-02-11T09:15:22Z",
    "fields": {"id": "8", "Title": "Close books", "Status": "Open"},
}


def _list_read(graph: respx.MockRouter, name: str = "Tasks") -> None:
    _ = graph.get(_LIST_ROUTE).mock(
        return_value=httpx.Response(
            200, json={"id": _LIST_ID, "displayName": name, "webUrl": _LIST_URL}
        )
    )


def _columns(graph: respx.MockRouter) -> respx.Route:
    _list_read(graph)
    return graph.get(_COLUMNS_ROUTE).mock(
        return_value=httpx.Response(200, json={"value": _COLUMNS})
    )


def _posts(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_ITEMS_ROUTE).mock(return_value=httpx.Response(201, json=_CREATED))


async def _agrees(question: str, about: str) -> str | None:
    assert question
    assert about
    return None


def _asking(asked: list[str]) -> Confirm:
    async def recording(question: str, about: str) -> str | None:
        assert about
        asked.append(question)
        return None

    return recording


async def _create(
    client: GraphServiceClient, fields: Mapping[str, str], confirm: Confirm = _agrees
) -> ListItemSummary:
    created = await create_list_item(client, list_uri=_LIST_URI, fields=fields, confirm=confirm)
    assert isinstance(created, ListItemSummary), "this call was answered with a question"
    return created


def _sent_fields(route: respx.Route) -> object:
    body = cast("Mapping[str, object]", json.loads(route.calls.last.request.content))
    return body["fields"]


async def test_it_posts_the_typed_fields_once_the_person_agrees(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    _ = _columns(graph)
    post = _posts(graph)
    asked: list[str] = []

    created = await _create(
        client,
        {
            "Title": "Close books",
            "Status": "Open",
            "Amount": "12.5",
            "Done": "false",
            "Due": "2026-01-31T00:00:00Z",
        },
        _asking(asked),
    )

    assert post.call_count == 1
    assert _sent_fields(post) == {
        "Title": "Close books",
        "Status": "Open",
        "Amount": 12.5,
        "Done": False,
        "Due": "2026-01-31T00:00:00Z",
    }
    (question,) = asked
    assert f"'Tasks' ({_LIST_URL})" in question
    assert "'Close books'" in question
    assert "Status: 'Open'" in question
    assert list_item_handle(created.uri) == ListItemHandle(_SITE_ID, _LIST_ID, "8")
    assert (
        created.web_url
        == "https://contoso.sharepoint.invalid/sites/Finance/Lists/Tasks/DispForm.aspx?ID=8"
    )


async def test_an_answer_given_before_the_list_was_renamed_adds_nothing(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    _ = _columns(graph)
    post = _posts(graph)
    first = await create_list_item(
        client,
        list_uri=_LIST_URI,
        fields={"Title": "Close books"},
        confirm=a_person_agrees(modern_context()),
    )
    _list_read(graph, "Issues")

    with pytest.raises(ToolError, match="given for a different request"):
        _ = await create_list_item(
            client,
            list_uri=_LIST_URI,
            fields={"Title": "Close books"},
            confirm=a_person_agrees(accepted(first, "add the row")),
        )

    assert not post.called


async def test_an_answer_given_for_other_fields_adds_nothing(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    _ = _columns(graph)
    post = _posts(graph)
    first = await create_list_item(
        client,
        list_uri=_LIST_URI,
        fields={"Title": "Close books"},
        confirm=a_person_agrees(modern_context()),
    )

    with pytest.raises(ToolError, match="given for a different request"):
        _ = await create_list_item(
            client,
            list_uri=_LIST_URI,
            fields={"Title": "Open books"},
            confirm=a_person_agrees(accepted(first, "add the row")),
        )

    assert not post.called


async def test_the_second_call_adds_the_row_that_the_person_agreed_to(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    _ = _columns(graph)
    post = _posts(graph)
    fields = {"Title": "Close books"}
    first = await create_list_item(
        client, list_uri=_LIST_URI, fields=fields, confirm=a_person_agrees(modern_context())
    )

    _ = await create_list_item(
        client,
        list_uri=_LIST_URI,
        fields=fields,
        confirm=a_person_agrees(accepted(first, "add the row")),
    )

    assert post.call_count == 1


async def test_a_declined_question_sends_nothing(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    _ = _columns(graph)
    post = _posts(graph)
    fields = {"Title": "Close books"}
    first = await create_list_item(
        client, list_uri=_LIST_URI, fields=fields, confirm=a_person_agrees(modern_context())
    )

    with pytest.raises(ToolError, match="No row was added."):
        _ = await create_list_item(
            client,
            list_uri=_LIST_URI,
            fields=fields,
            confirm=a_person_agrees(accepted(first, "do not add it")),
        )

    assert not post.called


@pytest.mark.parametrize(
    "fields",
    [
        {"Owner": "someone@contoso.sharepoint.invalid"},
        {"OwnerLookupId": "7"},
        {"Tags": "a"},
        {"Parent": "3"},
        {"ParentLookupId": "3"},
        {"Topic": "Finance"},
        {"Location": "0,0"},
        {"Created": "2026-01-31T00:00:00Z"},
        {"Secret": "x"},
        {"Missing": "x"},
        {"Status": "Pending"},
        {"Amount": "12 or 1"},
        {"Done": "yes"},
        {"Due": "next Friday"},
        {"Title": "Close books", "Owner": "someone@contoso.sharepoint.invalid"},
    ],
)
async def test_a_column_it_cannot_write_sends_nothing_and_asks_nobody(
    client: GraphServiceClient, graph: respx.MockRouter, fields: Mapping[str, str]
) -> None:
    _ = _columns(graph)
    post = _posts(graph)
    asked: list[str] = []

    with pytest.raises(ToolError):
        _ = await _create(client, fields, _asking(asked))

    assert not post.called
    assert asked == []


async def test_a_value_that_is_not_a_list_handle_makes_no_graph_call(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    with pytest.raises(ToolError):
        _ = await create_list_item(
            client, list_uri="Tasks", fields={"Title": "Close books"}, confirm=_agrees
        )

    assert not graph.calls


@pytest.mark.usefixtures("retry_sleeps")
async def test_a_post_graph_declines_is_never_sent_a_second_time(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    _ = _columns(graph)
    post = graph.post(_ITEMS_ROUTE).mock(return_value=httpx.Response(503))

    with pytest.raises(GraphUnavailable):
        _ = await _create(client, {"Title": "Close books"})

    assert post.call_count == 1
