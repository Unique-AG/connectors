from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
)
from fastmcp.tools import Tool
from mcp.types import (
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    InputResponse,
)
from mcp.types.version import LATEST_MODERN_VERSION
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.handles import (
    OnenotePageHandle,
    OnenoteSectionHandle,
    onenote_page_handle,
)
from office_365_mcp.shared.notes import write_state_for
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE_IDEMPOTENT, Confirm
from office_365_mcp.tools import onenote_delete_page as deleter
from office_365_mcp.tools.onenote_delete_page import DeletedPage, a_person_agrees, delete_page

_PAGE_ID = "1-SYNTHETICPAGE00000000000000000000!0-ABCDEF"

_PAGE_URI = OnenotePageHandle(_PAGE_ID).uri

_PAGE_PATH = f"/me/onenote/pages/{_PAGE_ID}"

_NOTEBOOK_ID = "NOTEBOOK1"

_NOTEBOOK_GET_PATH = f"/me/onenote/notebooks/{_NOTEBOOK_ID}"

_SECTION = {"id": "SECTION1", "displayName": "General"}
_NOTEBOOK = {"id": _NOTEBOOK_ID, "displayName": "Work"}


def _page_payload(
    *,
    page_id: str | None = _PAGE_ID,
    title: str | None = "Meeting notes",
    section: Mapping[str, object] | None = None,
    notebook: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": page_id,
        "title": title,
        "parentSection": dict(section) if section is not None else None,
        "parentNotebook": dict(notebook) if notebook is not None else None,
    }


def _notebook_payload(
    *,
    notebook_id: str = _NOTEBOOK_ID,
    name: str | None = "Work",
    is_shared: bool | None = False,
    user_role: str | None = "Owner",
) -> dict[str, object]:
    return {"id": notebook_id, "displayName": name, "isShared": is_shared, "userRole": user_role}


def _reads(graph: respx.MockRouter, payload: Mapping[str, object]) -> respx.Route:
    return graph.get(_PAGE_PATH).mock(return_value=httpx.Response(200, json=dict(payload)))


def _deletes(graph: respx.MockRouter, *, status: int = 204) -> respx.Route:
    return graph.delete(_PAGE_PATH).mock(return_value=httpx.Response(status))


def _notebook_route(
    graph: respx.MockRouter,
    *,
    notebook_id: str = _NOTEBOOK_ID,
    is_shared: bool | None = False,
    user_role: str | None = "Owner",
    name: str | None = "Work",
) -> respx.Route:
    payload = _notebook_payload(
        notebook_id=notebook_id, name=name, is_shared=is_shared, user_role=user_role
    )
    return graph.get(f"/me/onenote/notebooks/{notebook_id}").mock(
        return_value=httpx.Response(200, json=payload)
    )


async def _agrees(question: str, about: str) -> str | None:
    assert question, "the person was asked nothing at all"
    assert about, "the answer was bound to nothing"
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return "The page was not deleted."


async def _delete(
    client: GraphServiceClient, *, page: str = _PAGE_URI, confirm: Confirm = _agrees
) -> DeletedPage:
    answer = await delete_page(client, page=page, confirm=confirm)
    assert isinstance(answer, DeletedPage), "this call was answered with a question, not a delete"
    return answer


def _made(route: respx.Route) -> Sequence[Call]:
    return cast("Sequence[Call]", route.calls)


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    deleter.register(mcp, transport)
    tool = await mcp.get_tool(deleter.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestWhatItSendsToGraph:
    async def test_it_reads_checks_the_notebook_then_deletes_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        page_route = _reads(graph, _page_payload(section=_SECTION, notebook=_NOTEBOOK))
        _ = _notebook_route(graph)
        delete_route = _deletes(graph)

        _ = await _delete(client)

        assert page_route.call_count == 1
        assert delete_route.call_count == 1
        assert len(graph.calls) == 3, (
            "a delete costs the pre-read, the notebook audience read and the delete"
        )

    async def test_the_pre_read_happens_before_the_delete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _page_payload(section=_SECTION, notebook=_NOTEBOOK))
        _ = _notebook_route(graph)
        _ = _deletes(graph)

        _ = await _delete(client)

        made = cast("Sequence[Call]", graph.calls)
        assert [call.request.method for call in made] == ["GET", "GET", "DELETE"]
        assert made[0].request.url.path.endswith(_PAGE_PATH)
        assert made[1].request.url.path.endswith(_NOTEBOOK_GET_PATH)
        assert made[2].request.url.path.endswith(_PAGE_PATH)

    async def test_the_pre_read_asks_for_id_title_and_both_parents(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        page_route = _reads(graph, _page_payload(section=_SECTION, notebook=_NOTEBOOK))
        _ = _notebook_route(graph)
        _ = _deletes(graph)

        _ = await _delete(client)

        query = _made(page_route)[0].request.url.params
        assert query["$select"] == "id,title"
        assert query["$expand"] == "parentNotebook,parentSection"

    async def test_the_delete_carries_no_body(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _page_payload(section=_SECTION, notebook=_NOTEBOOK))
        _ = _notebook_route(graph)
        delete_route = _deletes(graph)

        _ = await _delete(client)

        assert delete_route.calls.last.request.content == b""

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_delete_graph_declines_is_retried_by_default(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _page_payload(section=_SECTION, notebook=_NOTEBOOK))
        _ = _notebook_route(graph)
        delete_route = graph.delete(_PAGE_PATH).mock(
            side_effect=[httpx.Response(503), httpx.Response(204)]
        )

        _ = await _delete(client)

        assert delete_route.call_count == 2, (
            "a delete is idempotent, so the SDK's default retry runs"
        )


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            OnenoteSectionHandle("SECTION1").uri,
            "1-SYNTHETICPAGE00000000000000000000!0-ABCDEF",
            "https://onenote.example.invalid/page/1-SYNTHETICPAGE",
            "Meeting notes",
            "",
            "   ",
            "onenote:///pages/",
            "onenote:///pages/%20",
        ],
    )
    async def test_a_value_that_is_not_a_page_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError):
            _ = await _delete(client, page=value)

        assert len(graph.calls) == 0, "a refused handle deletes nothing"

    async def test_the_refusal_names_the_tool_that_mints_a_page_handle(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="onenote_list_pages"):
            _ = await _delete(client, page="Meeting notes")

    async def test_a_section_handle_is_refused_by_name(self, client: GraphServiceClient) -> None:
        with pytest.raises(ToolError, match="section handle"):
            _ = await _delete(client, page=OnenoteSectionHandle("SECTION1").uri)


class TestWhatItAnswers:
    async def test_the_answer_names_the_title_section_and_notebook_it_deleted(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(
            graph, _page_payload(title="Meeting notes", section=_SECTION, notebook=_NOTEBOOK)
        )
        _ = _notebook_route(graph)
        _ = _deletes(graph)

        answer = await _delete(client)

        assert answer.title == "Meeting notes"
        assert answer.section_uri == OnenoteSectionHandle("SECTION1").uri
        assert answer.section_name == "General"
        assert answer.notebook_name == "Work"
        assert answer.deleted is True

    async def test_nulls_when_graph_names_no_parent_section_or_notebook(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _page_payload(section=None, notebook=None))
        _ = _deletes(graph)

        answer = await _delete(client)

        assert answer.section_uri is None
        assert answer.section_name is None
        assert answer.notebook_name is None
        assert answer.deleted is True


class TestGraphFailures:
    async def test_a_404_on_the_pre_read_is_a_not_found_and_nothing_is_deleted(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        page_route = graph.get(_PAGE_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )
        delete_route = _deletes(graph)

        with pytest.raises(GraphNotFound):
            _ = await _delete(client)

        assert page_route.call_count == 1
        assert delete_route.call_count == 0, "the pre-read failed before anything was deleted"

    async def test_a_404_on_the_delete_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _page_payload(section=_SECTION, notebook=_NOTEBOOK))
        _ = _notebook_route(graph)
        delete_route = graph.delete(_PAGE_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _delete(client)

        assert delete_route.call_count == 1

    async def test_a_403_on_the_delete_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _page_payload(section=_SECTION, notebook=_NOTEBOOK))
        _ = _notebook_route(graph)
        _ = graph.delete(_PAGE_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _delete(client)

    async def test_a_404_on_the_notebook_read_is_a_not_found_and_nothing_is_deleted(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        page_route = _reads(graph, _page_payload(notebook=_NOTEBOOK))
        notebook_route = graph.get(_NOTEBOOK_GET_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )
        delete_route = _deletes(graph)

        with pytest.raises(GraphNotFound):
            _ = await _delete(client)

        assert page_route.call_count == 1
        assert notebook_route.call_count == 1
        assert delete_route.call_count == 0

    async def test_the_call_example_reaches_graph_and_the_pre_read_is_what_a_403_refuses(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        example = cast("Mapping[str, str]", deleter.GRAPH_CALL_EXAMPLE)
        handle = onenote_page_handle(example["page"])
        assert handle is not None, "GRAPH_CALL_EXAMPLE's own page value is not a page handle"
        refused = graph.get(f"/me/onenote/pages/{handle.page_id}").mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _delete(client, page=example["page"])

        assert refused.call_count == 1


class TestConfirmationIsAlwaysAsked:
    async def test_a_private_unshared_notebook_is_still_asked_about(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _page_payload(section=_SECTION, notebook=_NOTEBOOK))
        _ = _notebook_route(graph, is_shared=False, user_role="Owner")
        delete_route = _deletes(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _delete(client, confirm=counting)

        assert len(asked) == 1, "a delete must always be confirmed, even in a private notebook"
        assert delete_route.call_count == 1

    async def test_a_refusal_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        page_route = _reads(graph, _page_payload(section=_SECTION, notebook=_NOTEBOOK))
        _ = _notebook_route(graph)
        delete_route = _deletes(graph)

        with pytest.raises(ToolError, match="The page was not deleted"):
            _ = await delete_page(client, page=_PAGE_URI, confirm=_refuses)

        assert delete_route.call_count == 0
        assert page_route.call_count == 1

    async def test_the_question_names_the_title_section_notebook_and_the_recycle_bin(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(
            graph, _page_payload(title="Meeting notes", section=_SECTION, notebook=_NOTEBOOK)
        )
        _ = _notebook_route(graph, is_shared=True, user_role="Owner", name="Work")
        _ = _deletes(graph)
        asked: list[str] = []
        bound: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            asked.append(question)
            bound.append(about)
            return None

        _ = await _delete(client, confirm=capturing)

        assert len(asked) == 1
        question = asked[0]
        assert "Meeting notes" in question
        assert "General" in question
        assert "Work" in question
        assert "no recycle bin" in question
        assert "cannot be undone" in question
        assert bound == [write_state_for("delete", _PAGE_ID)]

    async def test_the_question_names_who_the_notebook_belongs_to_when_shared(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _page_payload(section=_SECTION, notebook=_NOTEBOOK))
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        _ = _deletes(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _delete(client, confirm=capturing)

        assert "shared with other people" in asked[0]

    async def test_the_question_names_no_page_section_or_notebook_graph_left_unnamed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _page_payload(title=None, section=None, notebook=None))
        _ = _deletes(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _delete(client, confirm=capturing)

        assert "an untitled page" in asked[0]
        assert "an unnamed section" in asked[0]
        assert "an unnamed notebook" in asked[0]

    @pytest.mark.parametrize(
        "answer",
        [
            DeclinedElicitation(),
            CancelledElicitation(),
            AcceptedElicitation(data="keep the page"),
            RuntimeError("elicitation not supported"),
            ToolError("the client refused the request"),
        ],
        ids=["declined", "cancelled", "another-answer", "cannot-ask", "client-error"],
    )
    async def test_no_refusal_is_ever_raised(self, answer: object) -> None:
        confirm = a_person_agrees(_context(answer))

        refusal = await confirm(
            "Delete 'Meeting notes' from 'General' in 'Work'?", "synthetic-state"
        )

        assert isinstance(refusal, str)
        assert refusal

    async def test_a_refusal_this_tool_words_opens_by_saying_the_page_was_not_deleted(self) -> None:
        confirm = a_person_agrees(_context(DeclinedElicitation()))

        refusal = await confirm(
            "Delete 'Meeting notes' from 'General' in 'Work'?", "synthetic-state"
        )

        assert isinstance(refusal, str)
        assert refusal.startswith("The page was not deleted.")

    async def test_agreeing_answers_with_no_refusal(self) -> None:
        confirm = a_person_agrees(_context(AcceptedElicitation(data="delete")))

        assert await confirm("Delete 'Meeting notes'?", "synthetic-state") is None


def _context(answer: object) -> Context:
    class _Client:
        request_context: object = None

        async def elicit(self, message: str, response_type: object = None) -> object:
            assert message
            assert response_type is not None, "the caller must say what it expects back"
            if isinstance(answer, Exception):
                raise answer
            return answer

    return cast("Context", cast("object", _Client()))


class _ModernRequest:
    protocol_version: str = LATEST_MODERN_VERSION


def _modern_context(
    *, answers: Mapping[str, InputResponse] | None = None, state: str | None = None
) -> Context:
    class _Client:
        request_context: _ModernRequest = _ModernRequest()
        input_responses: Mapping[str, InputResponse] | None = answers
        request_state: str | None = state

        async def elicit(self, message: str, response_type: object = None) -> object:
            raise AssertionError(
                f"a connection with no back-channel was asked {message!r} over it, "
                + f"expecting {response_type!r} back"
            )

    return cast("Context", cast("object", _Client()))


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_reaches_the_delete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _page_payload(section=_SECTION, notebook=_NOTEBOOK))
        _ = _notebook_route(graph)
        delete_route = _deletes(graph)

        answer = await delete_page(
            client, page=_PAGE_URI, confirm=a_person_agrees(_modern_context())
        )

        assert isinstance(answer, InputRequiredResult)
        assert answer.request_state == write_state_for("delete", _PAGE_ID)
        assert delete_route.call_count == 0

    async def test_the_first_round_asks_the_question_this_tool_words(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(
            graph, _page_payload(title="Meeting notes", section=_SECTION, notebook=_NOTEBOOK)
        )
        _ = _notebook_route(graph)
        _ = _deletes(graph)

        answer = await delete_page(
            client, page=_PAGE_URI, confirm=a_person_agrees(_modern_context())
        )

        assert isinstance(answer, InputRequiredResult)
        requests = answer.input_requests or {}
        request = requests[next(iter(requests))]
        assert isinstance(request, ElicitRequest)
        params = request.params
        assert isinstance(params, ElicitRequestFormParams)
        assert "Meeting notes" in params.message

    async def test_the_second_round_deletes_under_the_id_it_was_agreed_to_by(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _page_payload(section=_SECTION, notebook=_NOTEBOOK))
        _ = _notebook_route(graph)
        delete_route = _deletes(graph)
        state = write_state_for("delete", _PAGE_ID)

        first = await delete_page(
            client, page=_PAGE_URI, confirm=a_person_agrees(_modern_context())
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))

        answer = await delete_page(
            client,
            page=_PAGE_URI,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": "delete"})},
                    state=state,
                )
            ),
        )

        assert isinstance(answer, DeletedPage)
        assert delete_route.call_count == 1

    async def test_an_answer_bound_to_another_request_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _page_payload(section=_SECTION, notebook=_NOTEBOOK))
        _ = _notebook_route(graph)
        delete_route = _deletes(graph)

        first = await delete_page(
            client, page=_PAGE_URI, confirm=a_person_agrees(_modern_context())
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await delete_page(
                client,
                page=_PAGE_URI,
                confirm=a_person_agrees(
                    _modern_context(
                        answers={key: ElicitResult(action="accept", content={"value": "delete"})},
                        state="synthetic-other-state",
                    )
                ),
            )

        assert delete_route.call_count == 0


class TestTheClientThatCannotAsk:
    async def test_a_client_that_cannot_ask_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _page_payload(section=_SECTION, notebook=_NOTEBOOK))
        _ = _notebook_route(graph)
        delete_route = _deletes(graph)

        class _CannotAsk:
            request_context: object = None

            async def elicit(self, message: str, response_type: object = None) -> object:
                assert message and response_type is not None
                raise RuntimeError("elicitation not supported")

        confirm = a_person_agrees(cast("Context", cast("object", _CannotAsk())))

        with pytest.raises(ToolError, match="does not support elicitation"):
            _ = await delete_page(client, page=_PAGE_URI, confirm=confirm)

        assert delete_route.call_count == 0


class TestHowItDeclaresItself:
    def test_the_permission_is_notes_readwrite(self) -> None:
        assert deleter.GRAPH_PERMISSIONS == ("Notes.ReadWrite",)

    def test_the_call_example_is_a_page_handle_and_nothing_else(self) -> None:
        assert set(deleter.GRAPH_CALL_EXAMPLE) == {"page"}

    async def test_the_call_example_is_accepted_by_the_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(deleter.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_it_takes_one_argument_and_no_others(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"page"}

    @pytest.mark.parametrize("word", ["client", "ctx", "context", "token", "graph"])
    async def test_no_wiring_of_this_server_is_published_as_an_argument(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_it_announces_itself_as_a_destructive_write(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None, (
            "a tool with no annotations joins the write surface by omission"
        )
        assert annotations.read_only_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["idempotentHint"]

    async def test_the_description_says_it_always_asks_and_cannot_be_undone(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = (tool.description or "").casefold()
        assert "always" in description
        assert "recycle bin" in description
        assert "cannot be undone" in description
        assert "onenote_read_page" in description
        assert "onenote_edit_page" in description
        assert "onenote_rename_page" in description

    def test_not_found_advice_points_at_the_lister(self) -> None:
        assert "onenote_list_pages" in deleter.GRAPH_NOT_FOUND
