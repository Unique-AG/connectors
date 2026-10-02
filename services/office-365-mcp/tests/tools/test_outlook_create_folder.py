import json
import re
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import AcceptedElicitation, DeclinedElicitation
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import FunctionTool
from fastmcp.tools.base import ToolResult
from mcp.types import (
    CallToolRequestParams,
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
from office_365_mcp.shared.handles import MailFolderHandle, MailMessageHandle
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    Confirmed,
    GraphAdviceMiddleware,
    ToolAdvice,
)
from office_365_mcp.tools import outlook_create_folder as creator
from office_365_mcp.tools.outlook_create_folder import CreatedFolder, a_person_agrees, create_folder

_PARENT_ID = "AQMkADAwSYNTHETIC-folder-0001"
_NEW_ID = "AQMkADAwSYNTHETIC-folder-0002"

_PARENT_REF = MailFolderHandle(_PARENT_ID).uri

_MAILBOX = "alex@example.invalid"

_TOP = "/me/mailFolders"
_CHILDREN = f"/me/mailFolders/{_PARENT_ID}/childFolders"
_SHARED_TOP = f"/users/{_MAILBOX}/mailFolders"
_SHARED_CHILDREN = f"/users/{_MAILBOX}/mailFolders/{_PARENT_ID}/childFolders"

_NAME = "Invoices 2026"

_NOT_CREATED = "No folder was created."

_TAKEN: dict[str, object] = {
    "error": {
        "code": "ErrorFolderExists",
        "message": "A folder with the specified name already exists.",
    }
}


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _declines(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOT_CREATED


async def _never_asked(question: str, about: str) -> Confirmed:
    raise AssertionError(f"a person was asked {question!r} about {about!r}")


def _stored(
    *, folder_id: str | None = _NEW_ID, name: str | None = _NAME, parent: str = _PARENT_ID
) -> dict[str, object]:
    return {
        "id": folder_id,
        "displayName": name,
        "parentFolderId": parent,
        "childFolderCount": 0,
        "unreadItemCount": 0,
        "totalItemCount": 0,
        "isHidden": False,
    }


def _posts(
    graph: respx.MockRouter, path: str = _TOP, payload: dict[str, object] | None = None
) -> respx.Route:
    return graph.post(path).mock(
        return_value=httpx.Response(201, json=payload if payload is not None else _stored())
    )


def _posted(graph: respx.MockRouter) -> list[str]:
    calls = cast("Sequence[Call]", graph.calls)
    return [call.request.url.path for call in calls if call.request.method == "POST"]


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


async def _create(
    client: GraphServiceClient,
    *,
    name: str = _NAME,
    parent_ref: str | None = None,
    mailbox: str | None = None,
    confirm: Confirm = _never_asked,
) -> CreatedFolder:
    answer = await create_folder(
        client, name=name, confirm=confirm, parent_ref=parent_ref, mailbox=mailbox
    )
    assert isinstance(answer, CreatedFolder), "the confirmation asked instead of answering"
    return answer


async def _registered(transport: httpx.AsyncClient) -> FunctionTool:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    creator.register(mcp, transport)
    tool = await mcp.get_tool(creator.TOOL_NAME)
    assert isinstance(tool, FunctionTool), "register left the tool off the server"
    return tool


def _properties(tool: FunctionTool) -> Mapping[str, Mapping[str, object]]:
    return cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])


class TestWhatItSendsToGraph:
    async def test_no_parent_posts_to_the_top_level_of_the_own_mailbox(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        top = _posts(graph)

        _ = await _create(client)

        assert top.call_count == 1
        assert _posted(graph) == ["/v1.0/me/mailFolders"]

    async def test_a_parent_posts_to_the_child_folders_of_that_folder(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        children = _posts(graph, _CHILDREN)

        _ = await _create(client, parent_ref=_PARENT_REF)

        assert children.call_count == 1
        assert len(_posted(graph)) == 1

    async def test_the_post_carries_the_name_and_no_hidden_flag(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        top = _posts(graph)

        _ = await _create(client, name="Receipts / 2026")

        assert _sent(top)["displayName"] == "Receipts / 2026"
        assert "isHidden" not in _sent(top)

    async def test_a_shared_mailbox_posts_to_that_mailbox(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        top = _posts(graph, _SHARED_TOP)
        children = _posts(graph, _SHARED_CHILDREN)

        _ = await _create(client, mailbox=_MAILBOX, confirm=_agrees)
        _ = await _create(client, parent_ref=_PARENT_REF, mailbox=_MAILBOX, confirm=_agrees)

        assert (top.call_count, children.call_count) == (1, 1)
        assert all(f"/users/{_MAILBOX}/" in path for path in _posted(graph))

    async def test_the_call_example_creates_a_folder_in_the_own_mailbox(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        top = _posts(graph)
        example = cast("dict[str, str]", creator.GRAPH_CALL_EXAMPLE)

        _ = await _create(client, name=example["name"])

        assert top.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_create_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        top = graph.post(_TOP).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _create(client)

        assert top.call_count == 1, "no_retry means one attempt, however Graph answers"


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "parent_ref",
        [
            "Finance",
            "inbox",
            _PARENT_ID,
            "outlook:///folders/",
            MailMessageHandle("AAMkAGI2SYNTHETIC-immutable-0001=").uri,
            "outlook:///rules/SYNTHETIC-rule-0001",
        ],
    )
    async def test_a_parent_that_is_not_a_folder_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, parent_ref: str
    ) -> None:
        with pytest.raises(ToolError, match="outlook:///folders/") as raised:
            _ = await _create(client, parent_ref=parent_ref)

        assert "omit `parent_ref`" in str(raised.value)
        assert _NOT_CREATED in str(raised.value)
        assert len(graph.calls) == 0


class TestWhatItAnswers:
    async def test_the_handle_and_the_name_are_read_off_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph, payload=_stored(name="Invoices 2026 (stored)"))

        answer = await _create(client)

        assert answer.uri == MailFolderHandle(_NEW_ID).uri
        assert answer.display_name == "Invoices 2026 (stored)"

    async def test_a_name_graph_did_not_report_answers_null(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph, payload=_stored(name=None))

        answer = await _create(client)

        assert answer.display_name is None

    async def test_a_create_that_names_no_id_is_a_programming_error(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph, payload=_stored(folder_id=None))

        with pytest.raises(AssertionError):
            _ = await _create(client)


class TestTheFailuresItPassesOn:
    async def test_a_refused_create_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_TOP).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _create(client)

    async def test_a_parent_graph_will_not_return_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_CHILDREN).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "ErrorItemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _create(client, parent_ref=_PARENT_REF)

    def test_the_not_found_advice_blames_the_parent_and_says_where_a_fresh_one_is(self) -> None:
        assert "`parent_ref`" in creator.GRAPH_NOT_FOUND
        assert "outlook_browse_folders" in creator.GRAPH_NOT_FOUND
        assert "no folder was created" in creator.GRAPH_NOT_FOUND


async def _advice(client: GraphServiceClient) -> str:
    advice = GraphAdviceMiddleware(
        {
            creator.TOOL_NAME: ToolAdvice(
                permissions=creator.GRAPH_PERMISSIONS,
                not_found=creator.GRAPH_NOT_FOUND,
                shown_by=creator.CHANGE_SHOWN_BY,
            )
        }
    )

    async def the_tool(context: MiddlewareContext[CallToolRequestParams]) -> ToolResult:
        _ = context
        _ = await _create(client)
        raise AssertionError("Graph refused nothing, so there is no advice to read")

    context = MiddlewareContext(
        message=CallToolRequestParams(name=creator.TOOL_NAME, arguments={"name": _NAME})
    )
    with pytest.raises(ToolError) as raised:
        _ = await advice.on_call_tool(context, the_tool)
    return str(raised.value)


class TestWhatTheModelIsTold:
    async def test_a_duplicate_name_is_a_conflict_and_not_a_bad_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_TOP).mock(return_value=httpx.Response(409, json=_TAKEN))

        message = await _advice(client)

        assert "an item that is already there prevents it" in message
        assert "Change the name" in message
        assert "A folder with the specified name already exists." in message
        assert "bad request" not in message

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_an_outage_says_to_look_with_outlook_browse_folders_before_a_second_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_TOP).mock(return_value=httpx.Response(503))

        message = await _advice(client)

        assert "Do not call this tool again first." in message
        assert "To see if the change is there, use outlook_browse_folders." in message


def _questions() -> tuple[list[tuple[str, str]], Confirm]:
    asked: list[tuple[str, str]] = []

    async def capturing(question: str, about: str) -> Confirmed:
        asked.append((question, about))
        return None

    return asked, capturing


class TestThePersonBeforeTheFolderIsCreated:
    async def test_the_signed_in_users_own_mailbox_asks_nobody(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        top = _posts(graph)
        children = _posts(graph, _CHILDREN)

        _ = await _create(client, confirm=_never_asked)
        _ = await _create(client, parent_ref=_PARENT_REF, confirm=_never_asked)

        assert (top.call_count, children.call_count) == (1, 1)

    async def test_a_shared_mailbox_is_asked_about_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        top = _posts(graph, _SHARED_TOP)
        asked, capturing = _questions()

        _ = await _create(client, mailbox=_MAILBOX, confirm=capturing)

        assert len(asked) == 1
        assert top.call_count == 1

    async def test_a_refusal_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph, _SHARED_TOP)

        with pytest.raises(ToolError, match=_NOT_CREATED):
            _ = await _create(client, mailbox=_MAILBOX, confirm=_declines)

        assert _posted(graph) == []

    async def test_the_question_names_the_folder_the_mailbox_and_the_level(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph, _SHARED_TOP)
        _ = _posts(graph, _SHARED_CHILDREN)
        asked, capturing = _questions()

        _ = await _create(client, mailbox=_MAILBOX, confirm=capturing)
        _ = await _create(client, parent_ref=_PARENT_REF, mailbox=_MAILBOX, confirm=capturing)

        (top, _), (inside, _) = asked
        assert f"Create the folder {_NAME!r} at the top level of the mailbox {_MAILBOX!r}?" in top
        assert f"Create the folder {_NAME!r} inside a folder of the mailbox {_MAILBOX!r}?" in (
            inside
        )
        for question in (top, inside):
            assert "That mailbox belongs to someone else, not to the signed-in user." in question
            sentences = re.split(r"(?<=[.?])\s+", question)
            assert max(len(sentence.split()) for sentence in sentences) <= 20, sentences

    async def test_the_agreement_is_bound_to_the_mailbox_the_name_and_the_parent(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.route(method="POST").mock(return_value=httpx.Response(201, json=_stored()))
        asked, capturing = _questions()

        calls: tuple[dict[str, str | None], ...] = (
            {"name": _NAME, "parent_ref": None, "mailbox": _MAILBOX},
            {"name": _NAME, "parent_ref": None, "mailbox": _MAILBOX},
            {"name": "Other", "parent_ref": None, "mailbox": _MAILBOX},
            {"name": _NAME, "parent_ref": _PARENT_REF, "mailbox": _MAILBOX},
            {"name": _NAME, "parent_ref": None, "mailbox": "pam@example.invalid"},
        )
        for call in calls:
            _ = await _create(
                client,
                name=cast("str", call["name"]),
                parent_ref=call["parent_ref"],
                mailbox=call["mailbox"],
                confirm=capturing,
            )

        bound = [about for _question, about in asked]
        assert bound[0] == bound[1]
        assert len({*bound}) == 4
        assert all(question not in about for question, about in asked)


def _context(answer: object) -> Context:
    class _Client:
        request_context: object = None

        async def elicit(self, message: str, response_type: object = None) -> object:
            assert message
            assert response_type is not None
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


def _the_question(answer: CreatedFolder | InputRequiredResult) -> tuple[str, str]:
    assert isinstance(answer, InputRequiredResult), "the question was never put to anybody"
    requests = answer.input_requests or {}
    assert len(requests) == 1, f"one question per call, and this one asked {sorted(requests)}"
    key = next(iter(requests))
    request = requests[key]
    assert isinstance(request, ElicitRequest)
    assert isinstance(request.params, ElicitRequestFormParams)
    schema = cast("Mapping[str, object]", request.params.requested_schema)
    properties = cast("Mapping[str, Mapping[str, object]]", schema["properties"])
    assert properties["value"]["enum"] == ["create", "do not create"]
    assert answer.request_state, "the answer is bound to nothing"
    return key, answer.request_state


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_reaches_the_create(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        top = _posts(graph, _SHARED_TOP)

        answer = await create_folder(
            client, name=_NAME, confirm=a_person_agrees(_modern_context()), mailbox=_MAILBOX
        )

        _ = _the_question(answer)
        assert top.call_count == 0, "an unanswered question created the folder anyway"

    async def test_the_second_round_creates_the_folder_it_was_agreed_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        top = _posts(graph, _SHARED_TOP)
        key, state = _the_question(
            await create_folder(
                client, name=_NAME, confirm=a_person_agrees(_modern_context()), mailbox=_MAILBOX
            )
        )

        answer = await create_folder(
            client,
            name=_NAME,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": "create"})},
                    state=state,
                )
            ),
            mailbox=_MAILBOX,
        )

        assert isinstance(answer, CreatedFolder)
        assert top.call_count == 1

    async def test_an_answer_bound_to_another_name_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph, _SHARED_TOP)
        key, state = _the_question(
            await create_folder(
                client, name=_NAME, confirm=a_person_agrees(_modern_context()), mailbox=_MAILBOX
            )
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await create_folder(
                client,
                name="Something else",
                confirm=a_person_agrees(
                    _modern_context(
                        answers={key: ElicitResult(action="accept", content={"value": "create"})},
                        state=state,
                    )
                ),
                mailbox=_MAILBOX,
            )

        assert _posted(graph) == []

    async def test_the_own_mailbox_creates_in_one_round(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        top = _posts(graph)

        answer = await create_folder(client, name=_NAME, confirm=a_person_agrees(_modern_context()))

        assert isinstance(answer, CreatedFolder)
        assert top.call_count == 1


class TestTheHandshakeEra:
    async def test_an_agreeing_person_gets_the_folder(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        top = _posts(graph, _SHARED_TOP)

        answer = await create_folder(
            client,
            name=_NAME,
            confirm=a_person_agrees(_context(AcceptedElicitation(data="create"))),
            mailbox=_MAILBOX,
        )

        assert isinstance(answer, CreatedFolder)
        assert top.call_count == 1

    @pytest.mark.parametrize(
        "answer",
        [DeclinedElicitation(), AcceptedElicitation(data="do not create")],
        ids=["declined", "another-answer"],
    )
    async def test_a_person_who_does_not_agree_gets_no_folder(
        self, client: GraphServiceClient, graph: respx.MockRouter, answer: object
    ) -> None:
        _ = _posts(graph, _SHARED_TOP)

        with pytest.raises(ToolError, match=_NOT_CREATED):
            _ = await create_folder(
                client, name=_NAME, confirm=a_person_agrees(_context(answer)), mailbox=_MAILBOX
            )

        assert _posted(graph) == []


class TestHowItDeclaresItself:
    def test_the_permissions_and_the_tool_that_shows_the_change(self) -> None:
        assert creator.GRAPH_PERMISSIONS == ("Mail.ReadWrite", "Mail.ReadWrite.Shared")
        assert creator.CHANGE_SHOWN_BY == ("outlook_browse_folders",)
        assert creator.STEP_CREATE == "create_folder"

    async def test_it_announces_itself_as_a_write_that_adds(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_ADDITIVE["idempotentHint"]

    async def test_it_takes_a_name_and_two_optional_arguments_in_a_plain_object(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert tool.parameters["type"] == "object"
        assert not {"anyOf", "oneOf", "allOf", "not"} & set(tool.parameters)
        assert set(_properties(tool)) == {"name", "parent_ref", "mailbox"}
        assert cast("Sequence[str]", tool.parameters["required"]) == ["name"]

    async def test_the_description_names_the_agreement_and_what_to_do_after_a_timeout(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = tool.description or ""
        assert (
            "This tool asks the user to agree before it changes a shared or delegated mailbox. "
            + "It changes the user's own mailbox without a question."
        ) in description
        assert "If a call times out, do not call this tool again first." in description
        assert "outlook_browse_folders does not show a folder named `name`" in description
        assert "outlook_move_mail" in description

    async def test_register_asks_through_the_context_it_is_given(
        self, transport: httpx.AsyncClient, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        top = _posts(graph, _SHARED_TOP)
        tool = await _registered(transport)

        answer = cast(
            "object",
            await tool.fn(name=_NAME, ctx=_modern_context(), mailbox=_MAILBOX, client=client),
        )

        assert isinstance(answer, InputRequiredResult)
        assert top.call_count == 0
