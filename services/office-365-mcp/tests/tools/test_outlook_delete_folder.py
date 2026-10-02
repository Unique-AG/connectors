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
    WRITE_DESTRUCTIVE,
    Confirm,
    Confirmed,
    GraphAdviceMiddleware,
    ToolAdvice,
)
from office_365_mcp.tools import outlook_delete_folder as deleter
from office_365_mcp.tools.outlook_delete_folder import DeletedFolder, a_person_agrees, delete_folder

_FOLDER_ID = "AQMkADAwSYNTHETIC-folder-0001"
_MOVED_ID = "AQMkADAwSYNTHETIC-folder-0001-moved"
_INBOX_ID = "AQMkADAwSYNTHETIC-inbox"
_DELETED_ITEMS_ID = "AQMkADAwSYNTHETIC-deleteditems"
_ROOT_ID = "AQMkADAwSYNTHETIC-msgfolderroot"
_SYNC_ISSUES_ID = "AQMkADAwSYNTHETIC-syncissues"
_CONFLICTS_ID = "AQMkADAwSYNTHETIC-conflicts"
_SENT_ITEMS_ID = "AQMkADAwSYNTHETIC-sentitems"

_OUTLOOK_NAMES = (
    "archive",
    "clutter",
    "conflicts",
    "conversationhistory",
    "drafts",
    "inbox",
    "junkemail",
    "localfailures",
    "outbox",
    "recoverableitemsdeletions",
    "scheduled",
    "searchfolders",
    "sentitems",
    "serverfailures",
)

_FOLDER_REF = MailFolderHandle(_FOLDER_ID).uri

_MAILBOX = "alex@example.invalid"

_OWN = "/me/mailFolders"
_SHARED = f"/users/{_MAILBOX}/mailFolders"

_NAME = "Projects"

_NOT_DELETED = "The folder was not deleted."


@pytest.fixture(autouse=True)
def no_well_known_folders(graph: respx.MockRouter) -> None:
    for under in (_OWN, _SHARED):
        for name in ("msgfolderroot", "syncissues", *_OUTLOOK_NAMES):
            _ = graph.get(f"{under}/{name}").mock(
                return_value=httpx.Response(
                    404, json={"error": {"code": "ErrorItemNotFound", "message": "not found"}}
                )
            )


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _declines(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOT_DELETED


async def _never_asked(question: str, about: str) -> Confirmed:
    raise AssertionError(f"a person was asked {question!r} about {about!r}")


def _folder(
    *,
    folder_id: str = _FOLDER_ID,
    name: str | None = _NAME,
    items: int | None = 12,
    subfolders: int | None = 3,
    parent: str = _INBOX_ID,
) -> dict[str, object]:
    return {
        "id": folder_id,
        "displayName": name,
        "totalItemCount": items,
        "childFolderCount": subfolders,
        "parentFolderId": parent,
    }


def _ready(
    graph: respx.MockRouter,
    *,
    under: str = _OWN,
    at: str = _FOLDER_ID,
    folder: dict[str, object] | None = None,
    moved: dict[str, object] | None = None,
) -> respx.Route:
    _ = graph.get(f"{under}/{at}").mock(
        return_value=httpx.Response(200, json=folder if folder is not None else _folder())
    )
    _ = graph.get(f"{under}/deleteditems").mock(
        return_value=httpx.Response(200, json={"id": _DELETED_ITEMS_ID})
    )
    return graph.post(f"{under}/{at}/move").mock(
        return_value=httpx.Response(
            200,
            json=moved
            if moved is not None
            else _folder(folder_id=_MOVED_ID, parent=_DELETED_ITEMS_ID),
        )
    )


def _exists(graph: respx.MockRouter, name: str, folder_id: str, *, under: str = _OWN) -> None:
    _ = graph.get(f"{under}/{name}").mock(return_value=httpx.Response(200, json={"id": folder_id}))


def _methods(graph: respx.MockRouter) -> list[str]:
    return [call.request.method for call in cast("Sequence[Call]", graph.calls)]


def _requests(graph: respx.MockRouter) -> list[httpx.Request]:
    return [call.request for call in cast("Sequence[Call]", graph.calls)]


def _read_names(graph: respx.MockRouter) -> list[str]:
    return [request.url.path.rsplit("/", 1)[-1] for request in _requests(graph)]


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


async def _delete(
    client: GraphServiceClient,
    *,
    folder_ref: str = _FOLDER_REF,
    mailbox: str | None = None,
    confirm: Confirm = _agrees,
) -> DeletedFolder:
    answer = await delete_folder(client, folder_ref=folder_ref, confirm=confirm, mailbox=mailbox)
    assert isinstance(answer, DeletedFolder), "the confirmation asked instead of answering"
    return answer


async def _registered(transport: httpx.AsyncClient) -> FunctionTool:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    deleter.register(mcp, transport)
    tool = await mcp.get_tool(deleter.TOOL_NAME)
    assert isinstance(tool, FunctionTool), "register left the tool off the server"
    return tool


class TestWhatItSendsToGraph:
    async def test_it_reads_the_folder_deleted_items_and_the_two_parents_and_then_moves_the_folder(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        move = _ready(graph)

        _ = await _delete(client)

        assert _methods(graph) == ["GET", "GET", "GET", "GET", "POST"]
        assert _read_names(graph) == [
            _FOLDER_ID,
            "deleteditems",
            "msgfolderroot",
            "syncissues",
            "move",
        ]
        assert _sent(move) == {"DestinationId": _DELETED_ITEMS_ID}

    async def test_the_reads_select_only_what_the_question_and_the_refusals_need(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        _ = await _delete(client)

        folder, deleted_items, root, sync_issues, _move = _requests(graph)
        assert set(folder.url.params["$select"].split(",")) == {
            "displayName",
            "totalItemCount",
            "childFolderCount",
            "parentFolderId",
        }
        assert deleted_items.url.path.endswith("/me/mailFolders/deleteditems")
        assert deleted_items.url.params["$select"] == "id"
        assert root.url.path.endswith("/me/mailFolders/msgfolderroot")
        assert root.url.params["$select"] == "id"
        assert sync_issues.url.path.endswith("/me/mailFolders/syncissues")
        assert sync_issues.url.params["$select"] == "id"

    async def test_it_never_erases_the_folder(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)
        erase = graph.route(method="DELETE").mock(return_value=httpx.Response(204))
        permanent = graph.post(f"{_OWN}/{_FOLDER_ID}/permanentDelete").mock(
            return_value=httpx.Response(204)
        )

        _ = await _delete(client)

        assert erase.call_count == 0
        assert permanent.call_count == 0

    async def test_a_shared_mailbox_reads_and_moves_in_that_mailbox(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        move = _ready(graph, under=_SHARED)

        _ = await _delete(client, mailbox=_MAILBOX)

        assert move.call_count == 1
        assert all(f"/users/{_MAILBOX}/" in request.url.path for request in _requests(graph))

    async def test_the_call_example_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        move = _ready(graph)
        example = cast("dict[str, str]", deleter.GRAPH_CALL_EXAMPLE)

        _ = await _delete(client, folder_ref=example["folder_ref"])

        assert move.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_move_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        move = _ready(graph)
        move.mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _delete(client)

        assert move.call_count == 1, "no_retry means one attempt, however Graph answers"


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "folder_ref",
        [
            _NAME,
            "deleteditems",
            _FOLDER_ID,
            "outlook:///folders/",
            MailMessageHandle("AAMkAGI2SYNTHETIC-immutable-0001=").uri,
            "outlook:///rules/SYNTHETIC-rule-0001",
        ],
    )
    async def test_anything_that_is_not_a_folder_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, folder_ref: str
    ) -> None:
        with pytest.raises(ToolError, match="outlook:///folders/") as raised:
            _ = await _delete(client, folder_ref=folder_ref, confirm=_never_asked)

        assert "Nothing was deleted." in str(raised.value)
        assert len(graph.calls) == 0

    @pytest.mark.parametrize("by", ["handle", "read"])
    async def test_deleted_items_itself_is_refused_before_anybody_is_asked(
        self, client: GraphServiceClient, graph: respx.MockRouter, by: str
    ) -> None:
        folder_id = _DELETED_ITEMS_ID if by == "handle" else _FOLDER_ID
        _ = graph.get(f"{_OWN}/{folder_id}").mock(
            return_value=httpx.Response(200, json=_folder(folder_id=_DELETED_ITEMS_ID))
        )
        _ = graph.get(f"{_OWN}/deleteditems").mock(
            return_value=httpx.Response(200, json={"id": _DELETED_ITEMS_ID})
        )

        with pytest.raises(ToolError, match="Deleted Items itself") as raised:
            _ = await _delete(
                client, folder_ref=MailFolderHandle(folder_id).uri, confirm=_never_asked
            )

        assert "This connector cannot erase mail or folders." in str(raised.value)
        assert _methods(graph) == ["GET", "GET"]

    async def test_a_folder_already_in_deleted_items_is_refused_before_anybody_is_asked(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        move = _ready(graph, folder=_folder(parent=_DELETED_ITEMS_ID))

        with pytest.raises(ToolError, match="already in Deleted Items") as raised:
            _ = await _delete(client, confirm=_never_asked)

        assert "Nothing was deleted." in str(raised.value)
        assert move.call_count == 0

    @pytest.mark.parametrize("name", ["inbox", "SentItems", "msgfolderroot", "syncissues"])
    async def test_a_well_known_name_in_a_handle_is_refused_before_any_call_to_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, name: str
    ) -> None:
        with pytest.raises(ToolError, match=f"Outlook creates the folder '{name}'") as raised:
            _ = await _delete(client, folder_ref=MailFolderHandle(name).uri, confirm=_never_asked)

        assert "Nothing was deleted." in str(raised.value)
        assert len(graph.calls) == 0

    async def test_the_inbox_at_the_top_level_is_refused_before_anybody_is_asked(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        move = _ready(
            graph, at=_INBOX_ID, folder=_folder(folder_id=_INBOX_ID, name="Inbox", parent=_ROOT_ID)
        )
        _exists(graph, "msgfolderroot", _ROOT_ID)
        _exists(graph, "inbox", _INBOX_ID)

        with pytest.raises(ToolError, match="Outlook creates the folder 'Inbox'") as raised:
            _ = await _delete(
                client, folder_ref=MailFolderHandle(_INBOX_ID).uri, confirm=_never_asked
            )

        assert "This tool does not move it. Nothing was deleted." in str(raised.value)
        assert str(raised.value).endswith(
            "If you call this tool again with the same arguments, the call will fail the same way."
        )
        assert move.call_count == 0
        assert sorted(_read_names(graph)[4:]) == sorted(_OUTLOOK_NAMES), "a name was not read"

    async def test_a_child_of_sync_issues_with_the_id_of_conflicts_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        move = _ready(
            graph,
            folder=_folder(folder_id=_CONFLICTS_ID, name="Conflicts", parent=_SYNC_ISSUES_ID),
        )
        _exists(graph, "syncissues", _SYNC_ISSUES_ID)
        _exists(graph, "conflicts", _CONFLICTS_ID)

        with pytest.raises(ToolError, match="Outlook creates the folder 'Conflicts'"):
            _ = await _delete(client, confirm=_never_asked)

        assert move.call_count == 0

    async def test_a_well_known_name_that_answers_not_found_is_skipped(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        move = _ready(
            graph,
            folder=_folder(folder_id=_SENT_ITEMS_ID, name="Sent Items", parent=_ROOT_ID),
        )
        _exists(graph, "msgfolderroot", _ROOT_ID)
        _exists(graph, "sentitems", _SENT_ITEMS_ID)

        with pytest.raises(ToolError, match="Outlook creates the folder 'Sent Items'"):
            _ = await _delete(client, confirm=_never_asked)

        assert move.call_count == 0
        read = _read_names(graph)
        assert "sentitems" in read
        assert "archive" in read, "a name that answered not found ended the reads"

    @pytest.mark.parametrize(
        ("name", "folder_id"),
        [("msgfolderroot", _ROOT_ID), ("syncissues", _SYNC_ISSUES_ID)],
    )
    async def test_a_parent_folder_is_refused_after_the_two_parent_reads(
        self, client: GraphServiceClient, graph: respx.MockRouter, name: str, folder_id: str
    ) -> None:
        move = _ready(graph, folder=_folder(folder_id=folder_id, name=name, parent="above"))
        _exists(graph, "msgfolderroot", _ROOT_ID)
        _exists(graph, "syncissues", _SYNC_ISSUES_ID)

        with pytest.raises(ToolError, match="Outlook creates the folder"):
            _ = await _delete(client, confirm=_never_asked)

        assert move.call_count == 0
        assert _methods(graph) == ["GET", "GET", "GET", "GET"]

    async def test_a_folder_deeper_inside_deleted_items_moves_to_its_top(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        move = _ready(graph, folder=_folder(parent="AQMkADAwSYNTHETIC-folder-in-the-bin"))

        _ = await _delete(client)

        assert move.call_count == 1

    async def test_a_user_folder_called_inbox_at_the_top_level_is_moved_after_the_well_known_reads(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        move = _ready(graph, folder=_folder(name="Inbox", parent=_ROOT_ID))
        _exists(graph, "msgfolderroot", _ROOT_ID)
        for name in _OUTLOOK_NAMES:
            _exists(graph, name, f"AQMkADAwSYNTHETIC-{name}")

        _ = await _delete(client)

        assert move.call_count == 1
        read = _read_names(graph)[4:-1]
        assert sorted(read) == sorted(_OUTLOOK_NAMES), "each documented name is read once"


class TestWhatItAnswers:
    async def test_the_handle_is_the_one_graph_gave_after_the_move(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(
            graph,
            moved=_folder(folder_id=_MOVED_ID, name="Projects (stored)", parent=_DELETED_ITEMS_ID),
        )

        answer = await _delete(client)

        assert answer.uri == MailFolderHandle(_MOVED_ID).uri
        assert answer.uri != _FOLDER_REF
        assert answer.display_name == "Projects (stored)"

    async def test_a_move_that_names_no_id_is_a_programming_error(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, moved={"displayName": _NAME})

        with pytest.raises(AssertionError):
            _ = await _delete(client)


class TestTheFailuresItPassesOn:
    async def test_a_folder_graph_will_not_return_is_a_not_found_and_nobody_is_asked(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        move = _ready(graph)
        _ = graph.get(f"{_OWN}/{_FOLDER_ID}").mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "ErrorItemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _delete(client, confirm=_never_asked)

        assert move.call_count == 0

    async def test_a_refused_move_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        move = _ready(graph)
        move.mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _delete(client)

    def test_the_not_found_advice_names_an_earlier_move_and_where_a_fresh_handle_is(
        self,
    ) -> None:
        assert "An earlier call of this tool can also have moved it" in deleter.GRAPH_NOT_FOUND
        assert "outlook_browse_folders" in deleter.GRAPH_NOT_FOUND
        assert "nothing was deleted" in deleter.GRAPH_NOT_FOUND

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_an_outage_says_to_look_with_outlook_browse_folders_before_a_second_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        move = _ready(graph)
        move.mock(return_value=httpx.Response(503))
        advice = GraphAdviceMiddleware(
            {
                deleter.TOOL_NAME: ToolAdvice(
                    permissions=deleter.GRAPH_PERMISSIONS,
                    not_found=deleter.GRAPH_NOT_FOUND,
                    shown_by=deleter.CHANGE_SHOWN_BY,
                )
            }
        )

        async def the_tool(context: MiddlewareContext[CallToolRequestParams]) -> ToolResult:
            _ = context
            _ = await _delete(client)
            raise AssertionError("Graph refused nothing, so there is no advice to read")

        with pytest.raises(ToolError) as raised:
            _ = await advice.on_call_tool(
                MiddlewareContext(message=CallToolRequestParams(name=deleter.TOOL_NAME)),
                the_tool,
            )

        assert "Do not call this tool again first." in str(raised.value)
        assert "To see if the change is there, use outlook_browse_folders." in str(raised.value)


def _questions() -> tuple[list[tuple[str, str]], Confirm]:
    asked: list[tuple[str, str]] = []

    async def capturing(question: str, about: str) -> Confirmed:
        asked.append((question, about))
        return None

    return asked, capturing


async def _asked(
    client: GraphServiceClient,
    graph: respx.MockRouter,
    *,
    mailbox: str | None = None,
    folder: dict[str, object] | None = None,
) -> str:
    _ = _ready(graph, under=_OWN if mailbox is None else _SHARED, folder=folder)
    asked, capturing = _questions()
    _ = await _delete(client, mailbox=mailbox, confirm=capturing)
    ((question, _about),) = asked
    return question


class TestThePersonBeforeTheFolderMoves:
    async def test_the_own_mailbox_is_asked_about_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        question = await _asked(client, graph)

        assert question
        assert _methods(graph) == ["GET", "GET", "GET", "GET", "POST"]

    async def test_a_refusal_moves_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        move = _ready(graph)

        with pytest.raises(ToolError, match=_NOT_DELETED):
            _ = await _delete(client, confirm=_declines)

        assert move.call_count == 0

    async def test_the_question_names_the_folder_what_it_holds_and_where_it_goes(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        question = await _asked(client, graph)

        assert question == (
            f"Delete the folder {_NAME!r}? This tool moves it to Deleted Items, with everything "
            + "in it. It holds 12 items and 3 subfolders. It stays recoverable in Deleted Items."
        )
        sentences = re.split(r"(?<=[.?])\s+", question)
        assert max(len(sentence.split()) for sentence in sentences) <= 20, sentences

    async def test_the_question_for_a_shared_mailbox_names_it_and_whose_it_is(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        question = await _asked(client, graph, mailbox=_MAILBOX)

        assert f"Delete the folder {_NAME!r} in the mailbox {_MAILBOX!r}?" in question
        assert "That mailbox belongs to someone else, not to the signed-in user." in question

    @pytest.mark.parametrize(
        ("items", "subfolders", "said"),
        [
            (1, 1, "It holds 1 item and 1 subfolder."),
            (0, 0, "It holds 0 items and 0 subfolders."),
            (
                None,
                None,
                "It holds an unknown number of items and an unknown number of subfolders.",
            ),
        ],
    )
    async def test_the_question_counts_what_graph_reported_and_nothing_it_did_not(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        items: int | None,
        subfolders: int | None,
        said: str,
    ) -> None:
        question = await _asked(client, graph, folder=_folder(items=items, subfolders=subfolders))

        assert said in question

    async def test_a_folder_graph_gives_no_name_is_named_by_its_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        question = await _asked(client, graph, folder=_folder(name=None))

        assert f"Delete the folder {_FOLDER_REF!r}?" in question

    async def test_the_agreement_is_bound_to_the_mailbox_and_the_folder(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(path__regex=r"/deleteditems$").mock(
            return_value=httpx.Response(200, json={"id": _DELETED_ITEMS_ID})
        )
        _ = graph.route(method="GET").mock(return_value=httpx.Response(200, json=_folder()))
        _ = graph.route(method="POST").mock(
            return_value=httpx.Response(200, json=_folder(folder_id=_MOVED_ID))
        )
        asked, capturing = _questions()

        calls: tuple[tuple[str, str | None], ...] = (
            (_FOLDER_REF, None),
            (_FOLDER_REF, None),
            (_FOLDER_REF, _MAILBOX),
            (MailFolderHandle("AQMkADAwSYNTHETIC-folder-0009").uri, None),
        )
        for folder_ref, mailbox in calls:
            _ = await _delete(client, folder_ref=folder_ref, mailbox=mailbox, confirm=capturing)

        bound = [about for _question, about in asked]
        assert bound[0] == bound[1]
        assert len({*bound}) == 3


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


def _the_question(answer: DeletedFolder | InputRequiredResult) -> tuple[str, str]:
    assert isinstance(answer, InputRequiredResult), "the question was never put to anybody"
    requests = answer.input_requests or {}
    assert len(requests) == 1, f"one question per call, and this one asked {sorted(requests)}"
    key = next(iter(requests))
    request = requests[key]
    assert isinstance(request, ElicitRequest)
    assert isinstance(request.params, ElicitRequestFormParams)
    assert "Deleted Items" in request.params.message
    schema = cast("Mapping[str, object]", request.params.requested_schema)
    properties = cast("Mapping[str, Mapping[str, object]]", schema["properties"])
    assert properties["value"]["enum"] == ["delete", "keep the folder"]
    assert answer.request_state, "the answer is bound to nothing"
    return key, answer.request_state


async def _first_round(client: GraphServiceClient) -> tuple[str, str]:
    return _the_question(
        await delete_folder(
            client, folder_ref=_FOLDER_REF, confirm=a_person_agrees(_modern_context())
        )
    )


def _accepted(key: str, state: str) -> Confirm:
    return a_person_agrees(
        _modern_context(
            answers={key: ElicitResult(action="accept", content={"value": "delete"})},
            state=state,
        )
    )


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_reaches_the_move(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        move = _ready(graph)

        _ = await _first_round(client)

        assert move.call_count == 0, "an unanswered question moved the folder anyway"

    async def test_the_second_round_moves_the_folder_it_was_agreed_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        move = _ready(graph)
        key, state = await _first_round(client)

        answer = await delete_folder(client, folder_ref=_FOLDER_REF, confirm=_accepted(key, state))

        assert isinstance(answer, DeletedFolder)
        assert move.call_count == 1

    async def test_an_answer_bound_to_another_mailbox_moves_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        own = _ready(graph)
        shared = _ready(graph, under=_SHARED)
        key, state = await _first_round(client)

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await delete_folder(
                client, folder_ref=_FOLDER_REF, confirm=_accepted(key, state), mailbox=_MAILBOX
            )

        assert (own.call_count, shared.call_count) == (0, 0)


class TestTheHandshakeEra:
    async def test_an_agreeing_person_gets_the_move(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        move = _ready(graph)

        answer = await delete_folder(
            client,
            folder_ref=_FOLDER_REF,
            confirm=a_person_agrees(_context(AcceptedElicitation(data="delete"))),
        )

        assert isinstance(answer, DeletedFolder)
        assert move.call_count == 1

    @pytest.mark.parametrize(
        "answer",
        [DeclinedElicitation(), AcceptedElicitation(data="keep the folder")],
        ids=["declined", "another-answer"],
    )
    async def test_a_person_who_does_not_agree_keeps_the_folder(
        self, client: GraphServiceClient, graph: respx.MockRouter, answer: object
    ) -> None:
        move = _ready(graph)

        with pytest.raises(ToolError, match=_NOT_DELETED):
            _ = await delete_folder(
                client, folder_ref=_FOLDER_REF, confirm=a_person_agrees(_context(answer))
            )

        assert move.call_count == 0


class TestHowItDeclaresItself:
    def test_the_permissions_and_the_tool_that_shows_the_change(self) -> None:
        assert deleter.GRAPH_PERMISSIONS == ("Mail.ReadWrite", "Mail.ReadWrite.Shared")
        assert deleter.CHANGE_SHOWN_BY == ("outlook_browse_folders",)
        assert (
            deleter.STEP_READ_FOLDER,
            deleter.STEP_READ_DELETED_ITEMS,
            deleter.STEP_MOVE,
        ) == ("mail_folder", "destination_folder", "move_folder")

    async def test_it_announces_itself_as_a_destructive_write_that_is_not_repeated(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_DESTRUCTIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_DESTRUCTIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_DESTRUCTIVE["idempotentHint"]

    async def test_it_takes_a_folder_and_a_mailbox_in_a_plain_object(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert tool.parameters["type"] == "object"
        assert not {"anyOf", "oneOf", "allOf", "not"} & set(tool.parameters)
        assert set(cast("Mapping[str, object]", tool.parameters["properties"])) == {
            "folder_ref",
            "mailbox",
        }
        assert cast("Sequence[str]", tool.parameters["required"]) == ["folder_ref"]

    async def test_the_description_says_it_moves_to_deleted_items_and_never_erases(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = tool.description or ""
        assert "Moves one mail folder to Deleted Items" in description
        assert "It never erases anything" in description
        assert "This tool always asks the user to agree, also for the user's own mailbox." in (
            description
        )
        assert "This tool refuses Deleted Items itself" in description
        assert (
            "It also refuses a folder that Outlook creates for every mailbox, such as Inbox."
            in description
        )
        assert "If a call times out, do not call this tool again first." in description
        assert "permanent" not in description.casefold()

    async def test_register_asks_through_the_context_it_is_given(
        self, transport: httpx.AsyncClient, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        move = _ready(graph)
        tool = await _registered(transport)

        answer = cast(
            "object", await tool.fn(folder_ref=_FOLDER_REF, ctx=_modern_context(), client=client)
        )

        assert isinstance(answer, InputRequiredResult)
        assert move.call_count == 0
