import json
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
from fastmcp.tools import FunctionTool, Tool
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

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound, GraphUnavailable
from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    OnenotePageHandle,
    OnenoteSectionHandle,
)
from office_365_mcp.shared.notes import OperationSummary, write_state_for
from office_365_mcp.shared.seam import WRITE_ADDITIVE, Confirm
from office_365_mcp.tools import onenote_copy_page as copier
from office_365_mcp.tools.onenote_copy_page import a_person_agrees, copy_page

_PAGE_ID = "1-SYNTHETICPAGE00000000000000000000!0-ABCDEF"
_SECTION_ID = "1-SYNTHETICSECTION0000!0-ABCDEF"
_NOTEBOOK_ID = "NOTEBOOK1"

_PAGE_URI = OnenotePageHandle(_PAGE_ID).uri
_SECTION_URI = OnenoteSectionHandle(_SECTION_ID).uri

_PAGE_GET_PATH = f"/me/onenote/pages/{_PAGE_ID}"
_COPY_PATH = f"/me/onenote/pages/{_PAGE_ID}/copyToSection"
_SECTION_GET_PATH = f"/me/onenote/sections/{_SECTION_ID}"
_NOTEBOOK_GET_PATH = f"/me/onenote/notebooks/{_NOTEBOOK_ID}"

_NOTEBOOK = {"id": _NOTEBOOK_ID, "displayName": "Work"}


def _page_payload(
    *, page_id: str | None = _PAGE_ID, title: str | None = "Meeting notes"
) -> dict[str, object]:
    return {"id": page_id, "title": title}


def _section_payload(
    *, section_id: str | None = _SECTION_ID, notebook: Mapping[str, object] | None = _NOTEBOOK
) -> dict[str, object]:
    return {"id": section_id, "parentNotebook": dict(notebook) if notebook is not None else None}


def _notebook_payload(
    *,
    notebook_id: str = _NOTEBOOK_ID,
    name: str | None = "Work",
    is_shared: bool | None = False,
    user_role: str | None = "Owner",
) -> dict[str, object]:
    return {"id": notebook_id, "displayName": name, "isShared": is_shared, "userRole": user_role}


def _operation_payload(
    *,
    operation_id: str | None = "1-SYNTHETICOPERATION0000!0-ABCDEF",
    status: str | None = "Running",
) -> dict[str, object]:
    return {
        "id": operation_id,
        "status": status,
        "percentComplete": None,
        "createdDateTime": "2026-01-01T00:00:00Z",
        "lastActionDateTime": "2026-01-01T00:00:00Z",
        "resourceLocation": None,
        "resourceId": None,
        "error": None,
    }


def _page_gets(graph: respx.MockRouter, payload: Mapping[str, object]) -> respx.Route:
    return graph.get(_PAGE_GET_PATH).mock(return_value=httpx.Response(200, json=dict(payload)))


def _section_gets(graph: respx.MockRouter, payload: Mapping[str, object]) -> respx.Route:
    return graph.get(_SECTION_GET_PATH).mock(return_value=httpx.Response(200, json=dict(payload)))


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


def _copies(
    graph: respx.MockRouter, *, status: int = 202, payload: Mapping[str, object] | None = None
) -> respx.Route:
    body = dict(payload) if payload is not None else _operation_payload()
    return graph.post(_COPY_PATH).mock(return_value=httpx.Response(status, json=body))


def _private(graph: respx.MockRouter) -> None:
    _ = _page_gets(graph, _page_payload())
    _ = _section_gets(graph, _section_payload())
    _ = _notebook_route(graph, is_shared=False, user_role="Owner")


async def _agrees(question: str, about: str) -> str | None:
    assert question, "the person was asked nothing at all"
    assert about, "the answer was bound to nothing"
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return "Nothing was copied."


async def _copy(
    client: GraphServiceClient,
    *,
    page: str = _PAGE_URI,
    to_section: str = _SECTION_URI,
    confirm: Confirm = _agrees,
) -> OperationSummary:
    answer = await copy_page(client, page=page, to_section=to_section, confirm=confirm)
    assert isinstance(answer, OperationSummary), (
        "this call was answered with a question, not an operation"
    )
    return answer


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


def _made(route: respx.Route) -> Sequence[Call]:
    return cast("Sequence[Call]", route.calls)


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    copier.register(mcp, transport)
    tool = await mcp.get_tool(copier.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestWhatItSendsToGraph:
    async def test_it_reads_then_copies_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private(graph)
        copy = _copies(graph)

        _ = await _copy(client)

        assert copy.call_count == 1
        assert len(graph.calls) == 4, (
            "the page pre-read, the section read, the notebook read, the copy"
        )

    async def test_the_copy_is_sent_with_only_the_destination_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private(graph)
        copy = _copies(graph)

        _ = await _copy(client)

        assert _sent(copy) == {"id": _SECTION_ID}

    async def test_no_group_or_site_keys_are_ever_sent(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private(graph)
        copy = _copies(graph)

        _ = await _copy(client)

        sent = _sent(copy)
        assert "groupId" not in sent
        assert "siteId" not in sent
        assert "siteCollectionId" not in sent

    async def test_the_copy_content_type_is_json(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private(graph)
        copy = _copies(graph)

        _ = await _copy(client)

        assert copy.calls.last.request.headers["content-type"] == "application/json"

    async def test_the_pre_read_asks_only_for_id_and_title(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        page_route = _page_gets(graph, _page_payload())
        _ = _section_gets(graph, _section_payload())
        _ = _notebook_route(graph, is_shared=False, user_role="Owner")
        _ = _copies(graph)

        _ = await _copy(client)

        query = _made(page_route)[0].request.url.params
        assert query["$select"] == "id,title"

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_copy_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private(graph)
        copy = graph.post(_COPY_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _copy(client)

        assert copy.call_count == 1, "no_retry means one attempt, however Graph answers"


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            OnenoteSectionHandle(_SECTION_ID).uri,
            _PAGE_ID,
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
            _ = await _copy(client, page=value)

        assert len(graph.calls) == 0, "a refused handle writes nothing"

    async def test_the_page_refusal_names_the_tool_that_mints_a_page_handle(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="onenote_list_pages"):
            _ = await _copy(client, page="Meeting notes")

    @pytest.mark.parametrize(
        "value",
        [
            _PAGE_URI,
            OnenoteNotebookHandle(_NOTEBOOK_ID).uri,
            _SECTION_ID,
            "",
            "   ",
            "onenote:///sections/",
        ],
    )
    async def test_a_value_that_is_not_a_section_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError):
            _ = await _copy(client, to_section=value)

        assert len(graph.calls) == 0, "a refused handle writes nothing"

    async def test_the_section_refusal_names_the_tools_that_mint_a_section_handle(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="onenote_list_notebooks"):
            _ = await _copy(client, to_section="a section, not a handle")

    async def test_the_page_handle_is_checked_before_the_section_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="page handle"):
            _ = await _copy(client, page="not a handle", to_section="also not a handle")

        assert len(graph.calls) == 0


class TestWhatItAnswers:
    async def test_the_answer_is_the_operation_graph_started(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private(graph)
        _ = _copies(
            graph,
            payload=_operation_payload(operation_id="1-OPERATION0000!0-ABCDEF", status="Running"),
        )

        answer = await _copy(client)

        assert answer.status == "Running"
        assert "1-OPERATION0000" in answer.uri

    async def test_an_operation_with_no_id_is_a_programming_error(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private(graph)
        _ = _copies(graph, payload=_operation_payload(operation_id=None))

        with pytest.raises(AssertionError):
            _ = await _copy(client)


class TestGraphFailures:
    async def test_a_404_on_the_copy_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private(graph)
        _ = graph.post(_COPY_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _copy(client)

    async def test_a_404_on_the_section_read_is_a_not_found_and_nothing_is_copied(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _page_gets(graph, _page_payload())
        _ = graph.get(_SECTION_GET_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )
        copy = _copies(graph)

        with pytest.raises(GraphNotFound):
            _ = await _copy(client)

        assert copy.call_count == 0

    async def test_a_403_on_the_copy_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private(graph)
        _ = graph.post(_COPY_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _copy(client)

    def test_not_found_advice_points_at_the_listers(self) -> None:
        assert "onenote_list_pages" in copier.GRAPH_NOT_FOUND
        assert "onenote_list_notebooks" in copier.GRAPH_NOT_FOUND


class TestThePersonBetweenTheCopyAndTheOthersInTheNotebook:
    async def test_the_users_own_unshared_notebook_is_copied_into_without_a_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private(graph)
        copy = _copies(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _copy(client, confirm=counting)

        assert asked == [], "the user's own private notebook was put to a person anyway"
        assert copy.call_count == 1

    async def test_a_shared_notebook_is_asked_about_and_a_refusal_copies_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _page_gets(graph, _page_payload())
        _ = _section_gets(graph, _section_payload())
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        copy = _copies(graph)

        with pytest.raises(ToolError, match="Nothing was copied"):
            _ = await _copy(client, confirm=_refuses)

        assert copy.call_count == 0

    async def test_a_notebook_the_user_does_not_own_is_asked_about(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _page_gets(graph, _page_payload())
        _ = _section_gets(graph, _section_payload())
        _ = _notebook_route(graph, is_shared=False, user_role="Contributor")
        copy = _copies(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _copy(client, confirm=counting)

        assert len(asked) == 1
        assert copy.call_count == 1

    async def test_the_question_names_the_page_the_notebook_and_the_reason(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _page_gets(graph, _page_payload(title="Meeting notes"))
        _ = _section_gets(graph, _section_payload())
        _ = _notebook_route(graph, is_shared=True, user_role="Owner", name="Work")
        _ = _copies(graph)
        asked: list[str] = []
        bound: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            asked.append(question)
            bound.append(about)
            return None

        _ = await _copy(client, confirm=capturing)

        assert len(asked) == 1
        question = asked[0]
        assert "Meeting notes" in question
        assert "Work" in question
        assert "shared with other people" in question
        assert bound == [write_state_for("copy_page", _PAGE_ID, _SECTION_ID)]

    async def test_the_question_names_no_title_the_page_has_none(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _page_gets(graph, _page_payload(title=None))
        _ = _section_gets(graph, _section_payload(notebook=None))
        _ = _copies(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _copy(client, confirm=capturing)

        assert "an untitled page" in asked[0]
        assert "an unnamed notebook" in asked[0]
        assert "whose sharing Microsoft did not report" in asked[0]

    async def test_about_is_the_same_for_two_identical_calls_and_different_for_a_changed_section(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _page_gets(graph, _page_payload())
        _ = graph.get(_SECTION_GET_PATH).mock(
            return_value=httpx.Response(200, json=_section_payload())
        )
        other_section_id = "1-OTHERSECTION0000!0-ABCDEF"
        _ = graph.get(f"/me/onenote/sections/{other_section_id}").mock(
            return_value=httpx.Response(200, json=_section_payload(section_id=other_section_id))
        )
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        _ = _copies(graph)
        bound: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert question
            bound.append(about)
            return None

        other_section_uri = OnenoteSectionHandle(other_section_id).uri
        _ = await _copy(client, confirm=capturing)
        _ = await _copy(client, confirm=capturing)
        _ = await _copy(client, to_section=other_section_uri, confirm=capturing)

        assert bound[0] == bound[1]
        assert bound[2] != bound[0]

    @pytest.mark.parametrize(
        "answer",
        [
            DeclinedElicitation(),
            CancelledElicitation(),
            AcceptedElicitation(data="do not copy"),
            RuntimeError("elicitation not supported"),
            ToolError("the client refused the request"),
        ],
        ids=["declined", "cancelled", "another-answer", "cannot-ask", "client-error"],
    )
    async def test_no_refusal_is_ever_raised(self, answer: object) -> None:
        confirm = a_person_agrees(_context(answer))

        refusal = await confirm("Copy this page?", "synthetic-state")

        assert isinstance(refusal, str)
        assert refusal

    async def test_a_refusal_this_tool_words_opens_by_saying_nothing_was_copied(self) -> None:
        confirm = a_person_agrees(_context(DeclinedElicitation()))

        refusal = await confirm("Copy this page?", "synthetic-state")

        assert isinstance(refusal, str)
        assert refusal.startswith("Nothing was copied.")

    async def test_agreeing_answers_with_no_refusal(self) -> None:
        confirm = a_person_agrees(_context(AcceptedElicitation(data="copy")))

        assert await confirm("Copy this page?", "synthetic-state") is None


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
    async def test_the_first_round_asks_and_never_reaches_the_copy(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _page_gets(graph, _page_payload())
        _ = _section_gets(graph, _section_payload())
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        copy = _copies(graph)

        answer = await copy_page(
            client,
            page=_PAGE_URI,
            to_section=_SECTION_URI,
            confirm=a_person_agrees(_modern_context()),
        )

        assert isinstance(answer, InputRequiredResult)
        assert answer.request_state == write_state_for("copy_page", _PAGE_ID, _SECTION_ID)
        assert copy.call_count == 0

    async def test_the_first_round_asks_the_question_this_tool_words(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _page_gets(graph, _page_payload())
        _ = _section_gets(graph, _section_payload())
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        _ = _copies(graph)

        answer = await copy_page(
            client,
            page=_PAGE_URI,
            to_section=_SECTION_URI,
            confirm=a_person_agrees(_modern_context()),
        )

        assert isinstance(answer, InputRequiredResult)
        requests = answer.input_requests or {}
        request = requests[next(iter(requests))]
        assert isinstance(request, ElicitRequest)
        params = request.params
        assert isinstance(params, ElicitRequestFormParams)
        assert "Meeting notes" in params.message
        assert "Work" in params.message

    async def test_the_second_round_copies_under_the_id_it_was_agreed_to_by(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _page_gets(graph, _page_payload())
        _ = _section_gets(graph, _section_payload())
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        copy = _copies(graph)
        state = write_state_for("copy_page", _PAGE_ID, _SECTION_ID)

        first = await copy_page(
            client,
            page=_PAGE_URI,
            to_section=_SECTION_URI,
            confirm=a_person_agrees(_modern_context()),
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))

        answer = await copy_page(
            client,
            page=_PAGE_URI,
            to_section=_SECTION_URI,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": "copy"})},
                    state=state,
                )
            ),
        )

        assert isinstance(answer, OperationSummary)
        assert copy.call_count == 1

    async def test_an_answer_bound_to_another_request_copies_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _page_gets(graph, _page_payload())
        _ = _section_gets(graph, _section_payload())
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        copy = _copies(graph)

        first = await copy_page(
            client,
            page=_PAGE_URI,
            to_section=_SECTION_URI,
            confirm=a_person_agrees(_modern_context()),
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await copy_page(
                client,
                page=_PAGE_URI,
                to_section=_SECTION_URI,
                confirm=a_person_agrees(
                    _modern_context(
                        answers={key: ElicitResult(action="accept", content={"value": "copy"})},
                        state="synthetic-other-state",
                    )
                ),
            )

        assert copy.call_count == 0

    async def test_a_pending_decline_is_honored_even_when_the_fresh_read_says_private(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _page_gets(graph, _page_payload())
        _ = _section_gets(graph, _section_payload())
        notebook_route = graph.get(_NOTEBOOK_GET_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_notebook_payload(is_shared=True, user_role="Owner")),
                httpx.Response(200, json=_notebook_payload(is_shared=False, user_role="Owner")),
            ]
        )
        copy = _copies(graph)

        first = await copy_page(
            client,
            page=_PAGE_URI,
            to_section=_SECTION_URI,
            confirm=a_person_agrees(_modern_context()),
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))
        state = first.request_state
        assert state is not None

        with pytest.raises(ToolError, match="Nothing was copied"):
            _ = await copy_page(
                client,
                page=_PAGE_URI,
                to_section=_SECTION_URI,
                confirm=a_person_agrees(
                    _modern_context(answers={key: ElicitResult(action="decline")}, state=state)
                ),
                answer_pending=True,
            )

        assert copy.call_count == 0
        assert notebook_route.call_count == 2


class TestTheClientThatCannotAsk:
    async def test_a_client_that_cannot_ask_copies_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _page_gets(graph, _page_payload())
        _ = _section_gets(graph, _section_payload())
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        copy = _copies(graph)

        class _CannotAsk:
            request_context: object = None

            async def elicit(self, message: str, response_type: object = None) -> object:
                assert message and response_type is not None
                raise RuntimeError("elicitation not supported")

        confirm = a_person_agrees(cast("Context", cast("object", _CannotAsk())))

        with pytest.raises(ToolError, match="does not support elicitation"):
            _ = await copy_page(client, page=_PAGE_URI, to_section=_SECTION_URI, confirm=confirm)

        assert copy.call_count == 0


class TestHowRegisterWiresThePendingAnswer:
    async def test_register_consults_a_pending_answer_the_fresh_read_alone_would_skip(
        self, transport: httpx.AsyncClient, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _page_gets(graph, _page_payload())
        _ = _section_gets(graph, _section_payload())
        notebook_route = graph.get(_NOTEBOOK_GET_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_notebook_payload(is_shared=True, user_role="Owner")),
                httpx.Response(200, json=_notebook_payload(is_shared=False, user_role="Owner")),
            ]
        )
        copy = _copies(graph)
        mcp: FastMCP = FastMCP(name="wiring-under-test")
        copier.register(mcp, transport)
        tool = await mcp.get_tool(copier.TOOL_NAME)
        assert tool is not None, "register left the tool off the server"
        assert isinstance(tool, FunctionTool)

        first = cast(
            "OperationSummary | InputRequiredResult",
            await tool.fn(
                page=_PAGE_URI, to_section=_SECTION_URI, ctx=_modern_context(), client=client
            ),
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))
        state = first.request_state
        assert state is not None

        with pytest.raises(ToolError, match="Nothing was copied"):
            _ = cast(
                "OperationSummary | InputRequiredResult",
                await tool.fn(
                    page=_PAGE_URI,
                    to_section=_SECTION_URI,
                    ctx=_modern_context(answers={key: ElicitResult(action="decline")}, state=state),
                    client=client,
                ),
            )

        assert copy.call_count == 0
        assert notebook_route.call_count == 2


class TestHowItDeclaresItself:
    def test_the_permission_is_notes_create(self) -> None:
        assert copier.GRAPH_PERMISSIONS == ("Notes.Create",)

    def test_the_call_example_is_a_page_and_a_section_handle(self) -> None:
        assert set(copier.GRAPH_CALL_EXAMPLE) == {"page", "to_section"}

    async def test_the_call_example_is_accepted_by_the_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(copier.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_it_takes_two_arguments_and_no_others(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"page", "to_section"}

    @pytest.mark.parametrize("word", ["client", "ctx", "context", "token", "graph"])
    async def test_no_wiring_of_this_server_is_published_as_an_argument(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_it_announces_itself_as_an_additive_write(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None, (
            "a tool with no annotations joins the write surface by omission"
        )
        assert annotations.read_only_hint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_ADDITIVE["idempotentHint"]

    async def test_the_description_says_it_is_not_the_copy_itself(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = (tool.description or "").casefold()
        assert "onenote_get_operation" in description
        assert "not safe to retry blindly" in description
        assert "does not copy the page itself" in description
