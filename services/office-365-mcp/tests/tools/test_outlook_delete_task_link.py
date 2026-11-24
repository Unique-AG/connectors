from collections.abc import Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from mcp.types import InputRequiredResult
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import GraphNotFound
from office_365_mcp.shared.seam import Confirm
from office_365_mcp.tools.outlook_delete_task_link import DeletedTaskLink, delete_task_link

_LIST_ID = "AAMkSYNTHETIClist0001"
_TASK_ID = "AAMkSYNTHETICtask0001"
_LINK_ID = "SYNTHETIC-link-0001"
_TASK = f"outlook:///tasks/{_LIST_ID}/{_TASK_ID}"
_LINK = f"{_TASK}/links/{_LINK_ID}"
_ONE_TASK = f"/me/todo/lists/{_LIST_ID}/tasks/{_TASK_ID}"
_ONE_LINK = f"{_ONE_TASK}/linkedResources/{_LINK_ID}"
_NOTHING_DELETED = "The link was not deleted."


def _link_is_there(graph: respx.MockRouter) -> None:
    _ = graph.get(_ONE_LINK).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": _LINK_ID,
                "webUrl": "https://example.invalid/report",
                "displayName": "Q3 report",
                "applicationName": "Outlook",
            },
        )
    )
    _ = graph.get(_ONE_TASK).mock(
        return_value=httpx.Response(200, json={"id": _TASK_ID, "title": "Book the venue"})
    )


def _deleted(graph: respx.MockRouter, status: int = 204) -> respx.Route:
    return graph.delete(_ONE_LINK).mock(return_value=httpx.Response(status))


async def _agrees(question: str, about: str) -> str | None:
    assert question
    assert about
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return _NOTHING_DELETED


async def _delete(
    client: GraphServiceClient, *, link: str = _LINK, confirm: Confirm = _agrees
) -> DeletedTaskLink:
    answer = await delete_task_link(client, link=link, confirm=confirm)
    assert isinstance(answer, DeletedTaskLink), "this call was answered with a question"
    return answer


class TestWhatItSendsToGraph:
    async def test_it_reads_the_link_and_the_task_and_then_deletes_the_link(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _link_is_there(graph)
        _ = _deleted(graph)

        answer = await _delete(client)

        made = cast("Sequence[Call]", graph.calls)
        assert [(call.request.method, call.request.url.path) for call in made] == [
            ("GET", f"/v1.0{_ONE_LINK}"),
            ("GET", f"/v1.0{_ONE_TASK}"),
            ("DELETE", f"/v1.0{_ONE_LINK}"),
        ]
        assert made[1].request.url.params["$select"] == "id,title"
        assert (answer.title, answer.deleted) == ("Q3 report", True)

    async def test_a_link_that_is_gone_after_the_read_is_reported_as_deleted(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _link_is_there(graph)
        _ = _deleted(graph, status=404)

        answer = await _delete(client)

        assert answer.deleted is True

    async def test_a_link_that_is_gone_before_the_read_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ONE_LINK).mock(return_value=httpx.Response(404))
        delete = _deleted(graph)

        with pytest.raises(GraphNotFound):
            _ = await _delete(client)

        assert delete.call_count == 0


class TestWhatItRefusesBeforeAnyCall:
    @pytest.mark.parametrize(
        "link",
        [_TASK, f"{_TASK}/attachments/{_LINK_ID}", f"{_TASK}/steps/{_LINK_ID}", "Q3 report"],
    )
    async def test_a_handle_that_is_not_a_link_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter, link: str
    ) -> None:
        with pytest.raises(ToolError, match="outlook_read_task") as raised:
            _ = await _delete(client, link=link)

        assert _NOTHING_DELETED in str(raised.value)
        assert cast("Sequence[Call]", graph.calls) == []


class TestThePersonBetweenTheReadAndTheDelete:
    async def test_it_always_asks_and_the_question_names_the_link_and_the_task(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _link_is_there(graph)
        _ = _deleted(graph)
        asked: list[tuple[str, str]] = []

        async def capture(question: str, about: str) -> str | None:
            asked.append((question, about))
            return None

        _ = await _delete(client, confirm=capture)

        [(question, about)] = asked
        assert question == (
            "Delete the link 'Q3 report' from the task 'Book the venue'? The item that the link "
            + "opens does not change. To get the link back, someone must add it again."
        )
        assert about

    async def test_a_person_who_declines_keeps_the_link(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _link_is_there(graph)
        delete = _deleted(graph)

        with pytest.raises(ToolError) as raised:
            _ = await _delete(client, confirm=_refuses)

        assert str(raised.value) == _NOTHING_DELETED
        assert delete.call_count == 0

    async def test_a_question_that_a_modern_client_must_answer_comes_back_before_the_delete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _link_is_there(graph)
        delete = _deleted(graph)
        pending = InputRequiredResult(input_requests={}, request_state="state")

        async def ask_back(question: str, about: str) -> InputRequiredResult:
            assert question
            assert about
            return pending

        answer = await delete_task_link(client, link=_LINK, confirm=ask_back)

        assert answer is pending
        assert delete.call_count == 0
