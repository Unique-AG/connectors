import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphUnavailable
from office_365_mcp.shared.handles import ListHandle, ListItemHandle
from office_365_mcp.shared.seam import Confirm
from office_365_mcp.tools.sharepoint_delete_list_item import DeletedListItem, delete_list_item

_SITE_ID = (
    "contoso.sharepoint.invalid,00000000-0000-4000-8000-00000000000a,"
    + "11111111-aaaa-bbbb-cccc-222222222222"
)
_LIST_ID = "00000000-0000-4000-8000-00000000000b"
_ITEM_URI = ListItemHandle(_SITE_ID, _LIST_ID, "7").uri
_ITEM_ROUTE = f"/sites/{_SITE_ID}/lists/{_LIST_ID}/items/7"
_NOT_FOUND = {"error": {"code": "itemNotFound", "message": "not found"}}


def _reads(graph: respx.MockRouter) -> None:
    _ = graph.get(_ITEM_ROUTE).mock(
        return_value=httpx.Response(
            200, json={"id": "7", "fields": {"id": "7", "Title": "Close books", "Status": "Open"}}
        )
    )


def _deletes(graph: respx.MockRouter, *responses: httpx.Response) -> respx.Route:
    return graph.delete(_ITEM_ROUTE).mock(side_effect=list(responses or [httpx.Response(204)]))


def _asking(asked: list[str], *, answer: str | None = None) -> Confirm:
    async def recording(question: str, about: str) -> str | None:
        assert about
        asked.append(question)
        return answer

    return recording


async def _delete(client: GraphServiceClient, confirm: Confirm) -> DeletedListItem:
    deleted = await delete_list_item(client, item_uri=_ITEM_URI, confirm=confirm)
    assert isinstance(deleted, DeletedListItem), "this call was answered with a question"
    return deleted


async def test_it_deletes_the_row_only_after_the_person_agrees_to_the_named_row(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    _reads(graph)
    delete = _deletes(graph)
    asked: list[str] = []

    async def agrees_before_the_delete(question: str, about: str) -> str | None:
        assert about
        assert not delete.called
        asked.append(question)
        return None

    deleted = await _delete(client, agrees_before_the_delete)

    (question,) = asked
    assert "'Close books'" in question
    assert "recycle bin" in question
    assert delete.call_count == 1
    request = delete.calls.last.request
    assert request.url.query == b""
    assert "if-match" not in request.headers
    assert "prefer" not in request.headers
    assert deleted == DeletedListItem(
        title="Close books", list_uri=ListHandle(_SITE_ID, _LIST_ID).uri, deleted=True
    )


async def test_the_confirmation_state_changes_when_the_row_is_renamed(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    states: list[str] = []

    async def noting(_question: str, about: str) -> str | None:
        states.append(about)
        return "not agreed"

    for title in ("Close books", "Open books"):
        _ = graph.get(_ITEM_ROUTE).mock(
            return_value=httpx.Response(200, json={"id": "7", "fields": {"Title": title}})
        )
        with pytest.raises(ToolError):
            _ = await delete_list_item(client, item_uri=_ITEM_URI, confirm=noting)

    assert states[0] != states[1]


async def test_a_declined_question_sends_nothing(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    _reads(graph)
    delete = _deletes(graph)
    asked: list[str] = []

    with pytest.raises(ToolError, match="The row was not moved to the recycle bin."):
        _ = await delete_list_item(
            client,
            item_uri=_ITEM_URI,
            confirm=_asking(asked, answer="The row was not moved to the recycle bin."),
        )

    assert len(asked) == 1
    assert not delete.called


@pytest.mark.usefixtures("retry_sleeps")
async def test_a_missing_row_on_the_delete_is_a_success_and_is_not_retried(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    _reads(graph)
    delete = _deletes(graph, httpx.Response(404, json=_NOT_FOUND), httpx.Response(204))

    deleted = await _delete(client, _asking([]))

    assert delete.call_count == 1
    assert deleted.deleted is True


@pytest.mark.usefixtures("retry_sleeps")
async def test_a_503_on_the_delete_is_not_retried(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    _reads(graph)
    delete = _deletes(graph, httpx.Response(503), httpx.Response(204))

    with pytest.raises(GraphUnavailable):
        _ = await _delete(client, _asking([]))

    assert delete.call_count == 1, "the SDK sent the delete again on its own"


@pytest.mark.parametrize("value", ["Tasks", ListHandle(_SITE_ID, _LIST_ID).uri])
async def test_a_value_that_is_not_an_item_handle_makes_no_graph_call(
    client: GraphServiceClient, graph: respx.MockRouter, value: str
) -> None:
    asked: list[str] = []

    with pytest.raises(ToolError):
        _ = await delete_list_item(client, item_uri=value, confirm=_asking(asked))

    assert not graph.calls
    assert asked == []
