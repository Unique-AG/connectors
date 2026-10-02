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
from office_365_mcp.shared.mail import OUTLOOK_FOLDER_NAMES
from office_365_mcp.shared.seam import (
    WRITE_IDEMPOTENT,
    Confirm,
    Confirmed,
    GraphAdviceMiddleware,
    ToolAdvice,
)
from office_365_mcp.tools import outlook_rename_folder as renamer
from office_365_mcp.tools.outlook_rename_folder import RenamedFolder, a_person_agrees, rename_folder

_FOLDER_ID = "AQMkADAwSYNTHETIC-folder-0001"
_FOLDER_REF = MailFolderHandle(_FOLDER_ID).uri
_INBOX_ID = "AQMkADAwSYNTHETIC-inbox"
_ROOT_ID = "AQMkADAwSYNTHETIC-msgfolderroot"

_MAILBOX = "alex@example.invalid"
_OTHER_MAILBOX = "pam@example.invalid"

_OWN_FOLDERS = "/me/mailFolders"
_SHARED_FOLDERS = f"/users/{_MAILBOX}/mailFolders"
_OWN = f"{_OWN_FOLDERS}/{_FOLDER_ID}"
_SHARED = f"{_SHARED_FOLDERS}/{_FOLDER_ID}"

_OLD_NAME = "Invoices"
_NAME = "Invoices 2025"

_NOT_RENAMED = "The folder was not renamed."


@pytest.fixture(autouse=True)
def no_well_known_folders(graph: respx.MockRouter) -> None:
    for under in (_OWN_FOLDERS, _SHARED_FOLDERS, f"/users/{_OTHER_MAILBOX}/mailFolders"):
        for name in OUTLOOK_FOLDER_NAMES:
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
    return _NOT_RENAMED


async def _never_asked(question: str, about: str) -> Confirmed:
    raise AssertionError(f"a person was asked {question!r} about {about!r}")


def _stored(
    *, folder_id: str | None = _FOLDER_ID, name: str | None = _NAME, parent: str = _INBOX_ID
) -> dict[str, object]:
    return {
        "id": folder_id,
        "displayName": name,
        "parentFolderId": parent,
        "childFolderCount": 2,
        "unreadItemCount": 0,
        "totalItemCount": 12,
    }


def _reads(
    graph: respx.MockRouter, path: str = _SHARED, name: str | None = _OLD_NAME
) -> respx.Route:
    return graph.get(path).mock(return_value=httpx.Response(200, json=_stored(name=name)))


def _patches(
    graph: respx.MockRouter, path: str = _OWN, payload: dict[str, object] | None = None
) -> respx.Route:
    return graph.patch(path).mock(
        return_value=httpx.Response(200, json=payload if payload is not None else _stored())
    )


def _exists(
    graph: respx.MockRouter, name: str, folder_id: str, *, under: str = _OWN_FOLDERS
) -> None:
    _ = graph.get(f"{under}/{name}").mock(return_value=httpx.Response(200, json={"id": folder_id}))


def _methods(graph: respx.MockRouter) -> list[str]:
    return [call.request.method for call in cast("Sequence[Call]", graph.calls)]


def _read_names(graph: respx.MockRouter) -> list[str]:
    calls = cast("Sequence[Call]", graph.calls)
    return [call.request.url.path.rsplit("/", 1)[-1] for call in calls]


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


async def _rename(
    client: GraphServiceClient,
    *,
    folder_ref: str = _FOLDER_REF,
    name: str = _NAME,
    mailbox: str | None = None,
    confirm: Confirm = _never_asked,
) -> RenamedFolder:
    answer = await rename_folder(
        client, folder_ref=folder_ref, name=name, confirm=confirm, mailbox=mailbox
    )
    assert isinstance(answer, RenamedFolder), "the confirmation asked instead of answering"
    return answer


async def _registered(transport: httpx.AsyncClient) -> FunctionTool:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    renamer.register(mcp, transport)
    tool = await mcp.get_tool(renamer.TOOL_NAME)
    assert isinstance(tool, FunctionTool), "register left the tool off the server"
    return tool


class TestWhatItSendsToGraph:
    async def test_the_own_mailbox_reads_the_folder_and_the_two_parents_and_then_patches_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph, _OWN)
        patch = _patches(graph)

        _ = await _rename(client)

        assert patch.call_count == 1
        assert _methods(graph) == ["GET", "GET", "GET", "PATCH"]
        names = _read_names(graph)
        assert (names[0], names[3]) == (_FOLDER_ID, _FOLDER_ID)
        assert sorted(names[1:3]) == ["msgfolderroot", "syncissues"]
        assert set(read.calls.last.request.url.params["$select"].split(",")) == {
            "id",
            "parentFolderId",
            "displayName",
        }

    async def test_the_patch_carries_only_the_new_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _OWN)
        patch = _patches(graph)

        _ = await _rename(client, name="Receipts / 2025")

        sent = _sent(patch)
        assert sent["displayName"] == "Receipts / 2025"
        assert set(sent) <= {"@odata.type", "displayName"}, sent

    async def test_a_shared_mailbox_reads_the_folder_once_and_then_patches_that_mailbox(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph)
        patch = _patches(graph, _SHARED)

        _ = await _rename(client, mailbox=_MAILBOX, confirm=_agrees)

        assert _methods(graph) == ["GET", "GET", "GET", "PATCH"]
        assert read.call_count == 1
        assert patch.call_count == 1

    async def test_the_call_example_renames_a_folder_in_the_own_mailbox(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        example = cast("dict[str, str]", renamer.GRAPH_CALL_EXAMPLE)
        _ = _reads(graph, _OWN)
        patch = _patches(graph)

        _ = await _rename(client, folder_ref=example["folder_ref"], name=example["name"])

        assert patch.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_rename_graph_declines_is_sent_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _OWN)
        patch = graph.patch(_OWN).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _rename(client)

        assert patch.call_count == 1


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "folder_ref",
        [
            _OLD_NAME,
            "inbox",
            _FOLDER_ID,
            "outlook:///folders/",
            MailMessageHandle("AAMkAGI2SYNTHETIC-immutable-0001=").uri,
            "outlook:///drafts/AAMkAGI2SYNTHETIC-draft-0001%3D",
        ],
    )
    async def test_anything_that_is_not_a_folder_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, folder_ref: str
    ) -> None:
        with pytest.raises(ToolError, match="outlook:///folders/") as raised:
            _ = await _rename(client, folder_ref=folder_ref)

        assert "Nothing was renamed." in str(raised.value)
        assert len(graph.calls) == 0

    @pytest.mark.parametrize("mailbox", [None, _MAILBOX], ids=["own-mailbox", "shared-mailbox"])
    @pytest.mark.parametrize("name", ["inbox", "SentItems", "msgfolderroot", "syncissues"])
    async def test_a_well_known_name_in_a_handle_is_refused_before_any_call_to_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, name: str, mailbox: str | None
    ) -> None:
        patch = _patches(graph)

        with pytest.raises(ToolError, match=f"Outlook creates the folder '{name}'") as raised:
            _ = await _rename(
                client, folder_ref=MailFolderHandle(name).uri, mailbox=mailbox, confirm=_never_asked
            )

        assert "This tool does not rename it. Nothing was renamed." in str(raised.value)
        assert len(graph.calls) == 0
        assert patch.call_count == 0

    @pytest.mark.parametrize(
        ("mailbox", "under"),
        [(None, _OWN_FOLDERS), (_MAILBOX, _SHARED_FOLDERS)],
        ids=["own-mailbox", "shared-mailbox"],
    )
    async def test_the_inbox_at_the_top_level_is_refused_before_anybody_is_asked(
        self, client: GraphServiceClient, graph: respx.MockRouter, mailbox: str | None, under: str
    ) -> None:
        _ = graph.get(f"{under}/{_INBOX_ID}").mock(
            return_value=httpx.Response(
                200, json=_stored(folder_id=_INBOX_ID, name="Inbox", parent=_ROOT_ID)
            )
        )
        patch = _patches(graph, f"{under}/{_INBOX_ID}")
        _exists(graph, "msgfolderroot", _ROOT_ID, under=under)
        _exists(graph, "inbox", _INBOX_ID, under=under)

        with pytest.raises(ToolError, match="Outlook creates the folder 'Inbox'") as raised:
            _ = await _rename(
                client,
                folder_ref=MailFolderHandle(_INBOX_ID).uri,
                mailbox=mailbox,
                confirm=_never_asked,
            )

        assert "This tool does not rename it. Nothing was renamed." in str(raised.value)
        assert str(raised.value).endswith(
            "If you call this tool again with the same arguments, the call will fail the same way."
        )
        assert patch.call_count == 0

    async def test_a_user_folder_called_inbox_at_the_top_level_is_renamed_with_no_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_OWN).mock(
            return_value=httpx.Response(200, json=_stored(name="Inbox", parent=_ROOT_ID))
        )
        patch = _patches(graph)
        for name in OUTLOOK_FOLDER_NAMES:
            _exists(graph, name, f"AQMkADAwSYNTHETIC-{name}")
        _exists(graph, "msgfolderroot", _ROOT_ID)

        _ = await _rename(client, confirm=_never_asked)

        assert patch.call_count == 1
        assert set(OUTLOOK_FOLDER_NAMES) <= set(_read_names(graph)), "a documented name was skipped"


class TestWhatItAnswers:
    async def test_the_handle_and_the_name_are_read_off_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _OWN)
        _ = _patches(graph, payload=_stored(name="Invoices 2025 (stored)"))

        answer = await _rename(client)

        assert answer.uri == _FOLDER_REF
        assert answer.display_name == "Invoices 2025 (stored)"

    async def test_a_rename_that_names_no_id_is_a_programming_error(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _OWN)
        _ = _patches(graph, payload=_stored(folder_id=None))

        with pytest.raises(AssertionError):
            _ = await _rename(client)


class TestTheFailuresItPassesOn:
    async def test_a_folder_graph_will_not_return_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _OWN)
        _ = graph.patch(_OWN).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "ErrorItemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _rename(client)

    async def test_a_missing_folder_in_another_mailbox_is_found_out_before_the_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_SHARED).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "ErrorItemNotFound", "message": "not found"}}
            )
        )
        patch = _patches(graph, _SHARED)

        with pytest.raises(GraphNotFound):
            _ = await _rename(client, mailbox=_MAILBOX, confirm=_never_asked)

        assert patch.call_count == 0

    async def test_a_refused_rename_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _OWN)
        _ = graph.patch(_OWN).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _rename(client)

    def test_the_not_found_advice_says_where_a_fresh_handle_is(self) -> None:
        assert "outlook_browse_folders" in renamer.GRAPH_NOT_FOUND
        assert "nothing was renamed" in renamer.GRAPH_NOT_FOUND

    async def test_a_name_another_folder_has_is_a_conflict_and_not_a_bad_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _OWN)
        _ = graph.patch(_OWN).mock(
            return_value=httpx.Response(
                409,
                json={
                    "error": {
                        "code": "ErrorFolderExists",
                        "message": "A folder with the specified name already exists.",
                    }
                },
            )
        )
        advice = GraphAdviceMiddleware(
            {renamer.TOOL_NAME: ToolAdvice(permissions=renamer.GRAPH_PERMISSIONS)}
        )

        async def the_tool(context: MiddlewareContext[CallToolRequestParams]) -> ToolResult:
            _ = context
            _ = await _rename(client)
            raise AssertionError("Graph refused nothing, so there is no advice to read")

        with pytest.raises(ToolError) as raised:
            _ = await advice.on_call_tool(
                MiddlewareContext(message=CallToolRequestParams(name=renamer.TOOL_NAME)),
                the_tool,
            )

        message = str(raised.value)
        assert "an item that is already there prevents it" in message
        assert "A folder with the specified name already exists." in message
        assert "bad request" not in message


def _questions() -> tuple[list[tuple[str, str]], Confirm]:
    asked: list[tuple[str, str]] = []

    async def capturing(question: str, about: str) -> Confirmed:
        asked.append((question, about))
        return None

    return asked, capturing


class TestThePersonBeforeTheFolderIsRenamed:
    async def test_the_signed_in_users_own_mailbox_asks_nobody(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _OWN)
        _ = _patches(graph)

        _ = await _rename(client, confirm=_never_asked)

        assert _methods(graph) == ["GET", "GET", "GET", "PATCH"]

    async def test_a_refusal_renames_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        patch = _patches(graph, _SHARED)

        with pytest.raises(ToolError, match=_NOT_RENAMED):
            _ = await _rename(client, mailbox=_MAILBOX, confirm=_declines)

        assert patch.call_count == 0

    async def test_the_question_names_the_folder_the_mailbox_and_the_new_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _patches(graph, _SHARED)
        asked, capturing = _questions()

        _ = await _rename(client, mailbox=_MAILBOX, confirm=capturing)

        ((question, _about),) = asked
        assert (
            f"Rename the folder {_OLD_NAME!r} in the mailbox {_MAILBOX!r} to {_NAME!r}?" in question
        )
        assert "That mailbox belongs to someone else, not to the signed-in user." in question
        sentences = re.split(r"(?<=[.?])\s+", question)
        assert max(len(sentence.split()) for sentence in sentences) <= 20, sentences

    async def test_a_folder_graph_gives_no_name_is_named_by_its_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, name=None)
        _ = _patches(graph, _SHARED)
        asked, capturing = _questions()

        _ = await _rename(client, mailbox=_MAILBOX, confirm=capturing)

        assert f"Rename the folder {_FOLDER_REF!r}" in asked[0][0]

    async def test_the_agreement_is_bound_to_the_mailbox_the_folder_and_the_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.route(method="GET").mock(return_value=httpx.Response(200, json=_stored()))
        _ = graph.route(method="PATCH").mock(return_value=httpx.Response(200, json=_stored()))
        asked, capturing = _questions()

        calls: tuple[tuple[str, str, str], ...] = (
            (_FOLDER_REF, _NAME, _MAILBOX),
            (_FOLDER_REF, _NAME, _MAILBOX),
            (_FOLDER_REF, "Other", _MAILBOX),
            (MailFolderHandle("AQMkADAwSYNTHETIC-folder-0009").uri, _NAME, _MAILBOX),
            (_FOLDER_REF, _NAME, _OTHER_MAILBOX),
        )
        for folder_ref, name, mailbox in calls:
            _ = await _rename(
                client, folder_ref=folder_ref, name=name, mailbox=mailbox, confirm=capturing
            )

        bound = [about for _question, about in asked]
        assert bound[0] == bound[1]
        assert len({*bound}) == 4


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


def _the_question(answer: RenamedFolder | InputRequiredResult) -> tuple[str, str]:
    assert isinstance(answer, InputRequiredResult), "the question was never put to anybody"
    requests = answer.input_requests or {}
    assert len(requests) == 1, f"one question per call, and this one asked {sorted(requests)}"
    key = next(iter(requests))
    request = requests[key]
    assert isinstance(request, ElicitRequest)
    assert isinstance(request.params, ElicitRequestFormParams)
    schema = cast("Mapping[str, object]", request.params.requested_schema)
    properties = cast("Mapping[str, Mapping[str, object]]", schema["properties"])
    assert properties["value"]["enum"] == ["rename", "do not rename"]
    assert answer.request_state, "the answer is bound to nothing"
    return key, answer.request_state


async def _first_round(client: GraphServiceClient) -> tuple[str, str]:
    return _the_question(
        await rename_folder(
            client,
            folder_ref=_FOLDER_REF,
            name=_NAME,
            confirm=a_person_agrees(_modern_context()),
            mailbox=_MAILBOX,
        )
    )


def _accepted(key: str, state: str) -> Confirm:
    return a_person_agrees(
        _modern_context(
            answers={key: ElicitResult(action="accept", content={"value": "rename"})},
            state=state,
        )
    )


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_reaches_the_rename(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        patch = _patches(graph, _SHARED)

        _ = await _first_round(client)

        assert patch.call_count == 0, "an unanswered question renamed the folder anyway"

    async def test_the_second_round_renames_the_folder_it_was_agreed_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        patch = _patches(graph, _SHARED)
        key, state = await _first_round(client)

        answer = await rename_folder(
            client,
            folder_ref=_FOLDER_REF,
            name=_NAME,
            confirm=_accepted(key, state),
            mailbox=_MAILBOX,
        )

        assert isinstance(answer, RenamedFolder)
        assert patch.call_count == 1

    async def test_an_answer_bound_to_another_name_renames_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        patch = _patches(graph, _SHARED)
        key, state = await _first_round(client)

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await rename_folder(
                client,
                folder_ref=_FOLDER_REF,
                name="Something else",
                confirm=_accepted(key, state),
                mailbox=_MAILBOX,
            )

        assert patch.call_count == 0


class TestTheHandshakeEra:
    async def test_an_agreeing_person_gets_the_rename(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        patch = _patches(graph, _SHARED)

        answer = await rename_folder(
            client,
            folder_ref=_FOLDER_REF,
            name=_NAME,
            confirm=a_person_agrees(_context(AcceptedElicitation(data="rename"))),
            mailbox=_MAILBOX,
        )

        assert isinstance(answer, RenamedFolder)
        assert patch.call_count == 1

    @pytest.mark.parametrize(
        "answer",
        [DeclinedElicitation(), AcceptedElicitation(data="do not rename")],
        ids=["declined", "another-answer"],
    )
    async def test_a_person_who_does_not_agree_gets_no_rename(
        self, client: GraphServiceClient, graph: respx.MockRouter, answer: object
    ) -> None:
        _ = _reads(graph)
        patch = _patches(graph, _SHARED)

        with pytest.raises(ToolError, match=_NOT_RENAMED):
            _ = await rename_folder(
                client,
                folder_ref=_FOLDER_REF,
                name=_NAME,
                confirm=a_person_agrees(_context(answer)),
                mailbox=_MAILBOX,
            )

        assert patch.call_count == 0


class TestHowItDeclaresItself:
    def test_the_permissions_and_the_steps(self) -> None:
        assert renamer.GRAPH_PERMISSIONS == ("Mail.ReadWrite", "Mail.ReadWrite.Shared")
        assert not hasattr(renamer, "CHANGE_SHOWN_BY"), (
            "a write that is safe to repeat gets the retry advice, which names no tool"
        )
        assert (renamer.STEP_READ_FOLDER, renamer.STEP_RENAME) == ("mail_folder", "rename_folder")

    async def test_it_announces_itself_as_a_write_that_can_be_repeated(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_IDEMPOTENT["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_IDEMPOTENT["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_IDEMPOTENT["idempotentHint"]

    async def test_it_takes_a_folder_a_name_and_a_mailbox_in_a_plain_object(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert tool.parameters["type"] == "object"
        assert not {"anyOf", "oneOf", "allOf", "not"} & set(tool.parameters)
        assert set(cast("Mapping[str, object]", tool.parameters["properties"])) == {
            "folder_ref",
            "name",
            "mailbox",
        }
        assert cast("Sequence[str]", tool.parameters["required"]) == ["folder_ref", "name"]

    async def test_the_description_names_the_agreement_and_the_safe_repeat(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = tool.description or ""
        assert (
            "This tool asks the user to agree before it changes a shared or delegated mailbox. "
            + "It changes the user's own mailbox without a question."
        ) in description
        assert (
            "This tool refuses a folder that Outlook creates for every mailbox, such as Inbox."
            in description
        )
        assert "This call is safe to repeat after a timeout." in description
        assert "The folder keeps its mail and its subfolders." in description

    async def test_register_asks_through_the_context_it_is_given(
        self, transport: httpx.AsyncClient, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        patch = _patches(graph, _SHARED)
        tool = await _registered(transport)

        answer = cast(
            "object",
            await tool.fn(
                folder_ref=_FOLDER_REF,
                name=_NAME,
                ctx=_modern_context(),
                mailbox=_MAILBOX,
                client=client,
            ),
        )

        assert isinstance(answer, InputRequiredResult)
        assert patch.call_count == 0
