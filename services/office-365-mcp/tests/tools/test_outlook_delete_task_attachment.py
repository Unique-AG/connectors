from collections.abc import Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from mcp.types import InputRequiredResult
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import GraphFailure
from office_365_mcp.shared.seam import Confirm
from office_365_mcp.tools.outlook_delete_task_attachment import (
    DeletedTaskAttachment,
    delete_task_attachment,
)

_LIST_ID = "AAMkSYNTHETIClist0001"
_TASK_ID = "AAMkSYNTHETICtask0001"
_FILE_ID = "AAMkSYNTHETICattachment0001"
_TASK = f"outlook:///tasks/{_LIST_ID}/{_TASK_ID}"
_FILE = f"{_TASK}/attachments/{_FILE_ID}"
_ONE_TASK = f"/me/todo/lists/{_LIST_ID}/tasks/{_TASK_ID}"
_ONE_FILE = f"{_ONE_TASK}/attachments/{_FILE_ID}"
_NOTHING_DELETED = "The file was not deleted."


def _file_is_there(graph: respx.MockRouter) -> None:
    _ = graph.get(_ONE_FILE).mock(
        return_value=httpx.Response(200, json={"id": _FILE_ID, "name": "Agenda.pdf"})
    )
    _ = graph.get(_ONE_TASK).mock(
        return_value=httpx.Response(200, json={"id": _TASK_ID, "title": "Book the venue"})
    )


def _deleted(graph: respx.MockRouter, status: int = 204) -> respx.Route:
    return graph.delete(_ONE_FILE).mock(return_value=httpx.Response(status))


async def _agrees(question: str, about: str) -> str | None:
    assert question
    assert about
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return _NOTHING_DELETED


async def _never_asked(question: str, about: str) -> str | None:
    raise AssertionError(f"a refused delete was put to a person: {question!r} ({about})")


async def _delete(
    client: GraphServiceClient, *, attachment: str = _FILE, confirm: Confirm = _agrees
) -> DeletedTaskAttachment:
    answer = await delete_task_attachment(client, attachment=attachment, confirm=confirm)
    assert isinstance(answer, DeletedTaskAttachment), "this call was answered with a question"
    return answer


class TestWhatItSendsToGraph:
    async def test_it_reads_the_file_name_and_the_task_and_then_deletes_the_file(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _file_is_there(graph)
        _ = _deleted(graph)

        answer = await _delete(client)

        made = cast("Sequence[Call]", graph.calls)
        assert [(call.request.method, call.request.url.path) for call in made] == [
            ("GET", f"/v1.0{_ONE_FILE}"),
            ("GET", f"/v1.0{_ONE_TASK}"),
            ("DELETE", f"/v1.0{_ONE_FILE}"),
        ]
        assert made[0].request.url.params["$select"] == "id,name"
        assert "$select" not in made[1].request.url.params
        assert (answer.name, answer.outcome) == ("Agenda.pdf", "deleted")

    async def test_a_file_that_is_gone_at_the_delete_is_reported_as_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _file_is_there(graph)
        _ = _deleted(graph, status=404)

        answer = await _delete(client)

        assert (answer.name, answer.outcome) == ("Agenda.pdf", "not_found")

    async def test_a_file_that_is_gone_before_the_question_is_reported_as_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ONE_FILE).mock(return_value=httpx.Response(404))
        delete = _deleted(graph)

        answer = await _delete(client, confirm=_never_asked)

        assert (answer.name, answer.outcome) == (None, "not_found")
        assert delete.call_count == 0

    async def test_a_task_that_is_gone_after_the_file_read_answers_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _file_is_there(graph)
        _ = graph.get(_ONE_TASK).mock(return_value=httpx.Response(404))
        delete = _deleted(graph)

        answer = await _delete(client, confirm=_never_asked)

        assert answer.outcome == "not_found"

        assert delete.call_count == 0


class TestWhatItRefusesBeforeAnyCall:
    @pytest.mark.parametrize(
        "attachment",
        [_TASK, f"{_TASK}/links/{_FILE_ID}", f"{_TASK}/steps/{_FILE_ID}", "Agenda.pdf"],
    )
    async def test_a_handle_that_is_not_a_file_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter, attachment: str
    ) -> None:
        with pytest.raises(ToolError, match="outlook_read_task") as raised:
            _ = await _delete(client, attachment=attachment)

        assert _NOTHING_DELETED in str(raised.value)
        assert cast("Sequence[Call]", graph.calls) == []


class TestThePersonBetweenTheReadAndTheDelete:
    async def test_it_always_asks_and_the_question_names_the_file_and_the_task(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _file_is_there(graph)
        _ = _deleted(graph)
        asked: list[tuple[str, str]] = []

        async def capture(question: str, about: str) -> str | None:
            asked.append((question, about))
            return None

        _ = await _delete(client, confirm=capture)

        [(question, about)] = asked
        assert question == (
            "Delete the file 'Agenda.pdf' from the task 'Book the venue'? This tool cannot get "
            + "the file back."
        )
        assert about

    async def test_a_person_who_declines_keeps_the_file(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _file_is_there(graph)
        delete = _deleted(graph)

        with pytest.raises(ToolError) as raised:
            _ = await _delete(client, confirm=_refuses)

        assert str(raised.value) == _NOTHING_DELETED
        assert delete.call_count == 0

    async def test_a_question_that_a_modern_client_must_answer_comes_back_before_the_delete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _file_is_there(graph)
        delete = _deleted(graph)
        pending = InputRequiredResult(input_requests={}, request_state="state")

        async def ask_back(question: str, about: str) -> InputRequiredResult:
            assert question
            assert about
            return pending

        answer = await delete_task_attachment(client, attachment=_FILE, confirm=ask_back)

        assert answer is pending
        assert delete.call_count == 0


class TestAFailedDelete:
    async def test_a_delete_that_graph_fails_is_sent_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _file_is_there(graph)
        delete = _deleted(graph, status=503)

        with pytest.raises(GraphFailure):
            _ = await _delete(client)

        assert delete.call_count == 1
