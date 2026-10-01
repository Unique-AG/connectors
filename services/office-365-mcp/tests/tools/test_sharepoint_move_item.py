import json
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from azure.core.credentials import AccessToken as GraphAccessToken
from fastmcp import Client, Context, FastMCP
from fastmcp.client.elicitation import ElicitRequestParams
from fastmcp.client.elicitation import ElicitResult as ClientAnswer
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.dependencies import AccessToken
from fastmcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
)
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import Tool
from fastmcp.tools.base import ToolResult
from mcp.shared.exceptions import MCPError
from mcp.types import (
    METHOD_NOT_FOUND,
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
from starlette.applications import Starlette

from office_365_mcp.app import create_app
from office_365_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig
from office_365_mcp.graph_client import (
    GraphFailure,
    GraphForbidden,
    GraphNotFound,
    GraphSettings,
    GraphUnavailable,
    create_graph_transport,
)
from office_365_mcp.shared.handles import (
    DriveFileHandle,
    DriveFolderHandle,
    drive_folder_handle,
    drive_item_handle,
)
from office_365_mcp.shared.notes import write_state_for
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Advised,
    Confirm,
    Confirmed,
    GraphAdviceMiddleware,
    ToolAdvice,
)
from office_365_mcp.tools import sharepoint_move_item as mover
from office_365_mcp.tools.sharepoint_move_item import MovedItem, a_person_agrees, move_item

GRAPH_V1 = "https://graph.microsoft.com/v1.0"

DRIVE_ID = "b!SYNTHETICDRIVE0000"
OTHER_DRIVE_ID = "b!SYNTHETICDRIVE0001"
ITEM_ID = "01SYNTHETICFILE0000"
FOLDER_ID = "01SYNTHETICFOLDER000"
OTHER_FOLDER_ID = "01SYNTHETICFOLDER001"
OLD_PARENT_ID = "01SYNTHETICPARENT000"
ROOT_ID = "01SYNTHETICROOT00000"

_ITEM = DriveFileHandle(DRIVE_ID, ITEM_ID).uri
_FOLDER = DriveFolderHandle(DRIVE_ID, FOLDER_ID).uri
_OTHER_FOLDER = DriveFolderHandle(DRIVE_ID, OTHER_FOLDER_ID).uri
_ROOT_BY_ALIAS = DriveFolderHandle(DRIVE_ID, "root").uri

_DRIVE_PATH = "/drives/b%21SYNTHETICDRIVE0000/items"
_ITEM_PATH = f"{_DRIVE_PATH}/{ITEM_ID}"
_FOLDER_PATH = f"{_DRIVE_PATH}/{FOLDER_ID}"
_OTHER_FOLDER_PATH = f"{_DRIVE_PATH}/{OTHER_FOLDER_ID}"
_ROOT_ALIAS_PATH = f"{_DRIVE_PATH}/root"

_NAME = "Budget.xlsx"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_NOTHING_MOVED = "Nothing was moved."
_NOT_FOUND = {"error": {"code": "itemNotFound", "message": "not found"}}
_NAME_EXISTS = {"error": {"code": "nameAlreadyExists", "message": "name exists"}}

_CLIENT_ID = "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061"
_CLIENT_TOKEN = "synthetic-fastmcp-session-token"
_OBO_TOKEN = "synthetic-obo-graph-token"


def _file_payload(
    *,
    name: str | None = _NAME,
    parent_id: str | None = OLD_PARENT_ID,
    parent_path: str | None = "/drive/root:/Reports",
    parent_name: str | None = None,
    root: bool = False,
) -> dict[str, object]:
    parent: dict[str, object] = {"driveId": DRIVE_ID, "driveType": "business"}
    for key, value in (("id", parent_id), ("path", parent_path), ("name", parent_name)):
        if value is not None:
            parent[key] = value
    payload: dict[str, object] = {
        "id": ITEM_ID,
        "name": name,
        "size": 2048,
        "webUrl": "https://contoso.sharepoint.invalid/sites/finance/Budget.xlsx",
        "lastModifiedDateTime": "2026-03-04T09:15:00Z",
        "file": {"mimeType": _XLSX},
        "parentReference": parent,
    }
    if root:
        payload["root"] = {}
    return payload


def _folder_payload(
    *,
    folder_id: str = FOLDER_ID,
    name: str | None = "Archive",
    parent_path: str | None = "/drive/root:",
    root: bool = False,
    a_folder: bool = True,
) -> dict[str, object]:
    payload: dict[str, object] = {"id": folder_id, "name": name}
    if a_folder:
        payload["folder"] = {"childCount": 3}
    else:
        payload["file"] = {"mimeType": _XLSX}
    if root:
        payload["root"] = {}
        payload["parentReference"] = {"driveId": DRIVE_ID, "driveType": "business"}
    else:
        parent: dict[str, object] = {"driveId": DRIVE_ID, "id": ROOT_ID}
        if parent_path is not None:
            parent["path"] = parent_path
        payload["parentReference"] = parent
    return payload


def _moved_payload(*, into: str = FOLDER_ID) -> dict[str, object]:
    return {
        **_file_payload(),
        "parentReference": {"driveId": DRIVE_ID, "id": into, "path": "/drive/root:/Archive"},
    }


def _reads(
    graph: respx.MockRouter,
    *,
    item: Mapping[str, object] | None = None,
    folder: Mapping[str, object] | None = None,
    folder_path: str = _FOLDER_PATH,
) -> tuple[respx.Route, respx.Route]:
    item_route = graph.get(_ITEM_PATH).mock(
        return_value=httpx.Response(200, json=dict(item or _file_payload()))
    )
    folder_route = graph.get(folder_path).mock(
        return_value=httpx.Response(200, json=dict(folder or _folder_payload()))
    )
    return item_route, folder_route


def _patches(graph: respx.MockRouter, response: httpx.Response | None = None) -> respx.Route:
    return graph.patch(_ITEM_PATH).mock(
        return_value=response or httpx.Response(200, json=_moved_payload())
    )


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _refuses(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOTHING_MOVED


async def _move(
    client: GraphServiceClient,
    *,
    item: str = _ITEM,
    to_folder: str = _FOLDER,
    confirm: Confirm = _agrees,
) -> MovedItem:
    answer = await move_item(client, item=item, to_folder=to_folder, confirm=confirm)
    assert isinstance(answer, MovedItem), "this call was answered with a question, not a move"
    return answer


def _made(router: respx.MockRouter) -> Sequence[Call]:
    return cast("Sequence[Call]", router.calls)


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    mover.register(mcp, transport)
    tool = await mcp.get_tool(mover.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


async def _advised(client: GraphServiceClient) -> str:
    async def moving(context: MiddlewareContext[CallToolRequestParams]) -> ToolResult:
        _ = context
        _ = await _move(client)
        raise AssertionError("the move answered, so there is no Graph failure to advise on")

    advice = GraphAdviceMiddleware(
        {
            mover.TOOL_NAME: ToolAdvice(
                permissions=mover.GRAPH_PERMISSIONS, not_found=mover.GRAPH_NOT_FOUND
            )
        }
    )
    context = MiddlewareContext(message=CallToolRequestParams(name=mover.TOOL_NAME, arguments={}))
    with pytest.raises(ToolError) as raised:
        _ = await advice.on_call_tool(context, moving)
    return str(raised.value)


class TestThePersonBeforeTheMove:
    async def test_a_refusal_moves_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        patch = _patches(graph)

        with pytest.raises(ToolError, match=_NOTHING_MOVED):
            _ = await _move(client, confirm=_refuses)

        assert patch.call_count == 0, "a declined move still reached the drive"

    async def test_the_question_carries_both_locations(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _patches(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert about
            asked.append(question)
            return None

        _ = await _move(client, confirm=capturing)

        assert asked == ["Move 'Budget.xlsx' from '/Reports' to '/Archive'?"]

    async def test_the_question_names_the_top_folder_of_the_drive_in_words(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(
            graph,
            item=_file_payload(parent_path="/drive/root:"),
            folder=_folder_payload(parent_path="/drive/root:/Reports/2026"),
        )
        _ = _patches(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert about
            asked.append(question)
            return None

        _ = await _move(client, confirm=capturing)

        assert asked == [
            "Move 'Budget.xlsx' from the top folder of the drive to '/Reports/2026/Archive'?"
        ]

    async def test_a_move_into_the_top_folder_is_asked_in_words(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(
            graph,
            folder=_folder_payload(folder_id=ROOT_ID, name="root", root=True),
            folder_path=_ROOT_ALIAS_PATH,
        )
        _ = _patches(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert about
            asked.append(question)
            return None

        _ = await _move(client, to_folder=_ROOT_BY_ALIAS, confirm=capturing)

        assert asked == ["Move 'Budget.xlsx' from '/Reports' to the top folder of the drive?"]

    async def test_the_question_decodes_graphs_percent_encoded_path(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, item=_file_payload(parent_path="/drive/root:/Q1%20Reports"))
        _ = _patches(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert about
            asked.append(question)
            return None

        _ = await _move(client, confirm=capturing)

        assert "'/Q1 Reports'" in asked[0]

    async def test_the_question_falls_back_to_the_parent_name_without_a_path(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(
            graph,
            item=_file_payload(parent_path=None, parent_name="Reports"),
            folder=_folder_payload(parent_path=None),
        )
        _ = _patches(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert about
            asked.append(question)
            return None

        _ = await _move(client, confirm=capturing)

        assert asked == ["Move 'Budget.xlsx' from 'Reports' to 'Archive'?"]

    async def test_the_question_names_nothing_graph_left_unnamed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(
            graph,
            item=_file_payload(name=None, parent_path=None),
            folder=_folder_payload(name=None),
        )
        _ = _patches(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert about
            asked.append(question)
            return None

        _ = await _move(client, confirm=capturing)

        assert asked == ["Move an unnamed item from an unnamed folder to an unnamed folder?"]

    async def test_the_question_is_asked_after_both_reads_and_before_the_patch(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        patch = _patches(graph)
        calls_when_asked: list[int] = []

        async def watching(question: str, about: str) -> Confirmed:
            assert question and about
            calls_when_asked.append(len(graph.calls))
            return None

        _ = await _move(client, confirm=watching)

        assert calls_when_asked == [2], "the question came before a read or after the patch"
        assert patch.call_count == 1

    async def test_the_answer_is_bound_to_the_drive_the_item_and_the_destination(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = graph.get(_OTHER_FOLDER_PATH).mock(
            return_value=httpx.Response(200, json=_folder_payload(folder_id=OTHER_FOLDER_ID))
        )
        _ = _patches(graph)
        bound: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert question
            bound.append(about)
            return None

        _ = await _move(client, confirm=capturing)
        _ = await _move(client, confirm=capturing)
        _ = await _move(client, to_folder=_OTHER_FOLDER, confirm=capturing)

        assert bound[0] == write_state_for(mover.TOOL_NAME, DRIVE_ID, ITEM_ID, FOLDER_ID)
        assert bound[1] == bound[0]
        assert bound[2] == write_state_for(mover.TOOL_NAME, DRIVE_ID, ITEM_ID, OTHER_FOLDER_ID)


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


class TestHowTheQuestionReachesAPerson:
    @pytest.mark.parametrize(
        "answer",
        [
            DeclinedElicitation(),
            CancelledElicitation(),
            AcceptedElicitation(data="do not move"),
            MCPError(METHOD_NOT_FOUND, "Method not found"),
            ToolError("the client refused the request"),
        ],
        ids=["declined", "cancelled", "another-answer", "cannot-ask", "client-error"],
    )
    async def test_every_answer_but_agreeing_is_a_refusal(self, answer: object) -> None:
        confirm = a_person_agrees(_context(answer))

        refusal = await confirm("Move 'Budget.xlsx' from '/Reports' to '/Archive'?", "state")

        assert isinstance(refusal, str)
        assert refusal

    async def test_a_refusal_this_tool_words_opens_by_saying_nothing_was_moved(self) -> None:
        confirm = a_person_agrees(_context(DeclinedElicitation()))

        refusal = await confirm("Move 'Budget.xlsx' from '/Reports' to '/Archive'?", "state")

        assert isinstance(refusal, str)
        assert refusal.startswith(_NOTHING_MOVED)

    async def test_agreeing_answers_with_no_refusal(self) -> None:
        confirm = a_person_agrees(_context(AcceptedElicitation(data="move")))

        assert await confirm("Move 'Budget.xlsx' from '/Reports' to '/Archive'?", "state") is None


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
                f"a connection with no back-channel was asked {message!r} over it, expecting "
                + f"{response_type!r} back"
            )

    return cast("Context", cast("object", _Client()))


def _the_question(answer: object) -> tuple[str, str, str, str]:
    assert isinstance(answer, InputRequiredResult), "the question was never put to anybody"
    requests = answer.input_requests or {}
    assert len(requests) == 1, f"one question per call, and this one asked {sorted(requests)}"
    key = next(iter(requests))
    request = requests[key]
    assert isinstance(request, ElicitRequest)
    params = request.params
    assert isinstance(params, ElicitRequestFormParams)
    schema = cast("Mapping[str, object]", params.requested_schema)
    properties = cast("Mapping[str, object]", schema["properties"])
    choices = cast("Sequence[str]", cast("Mapping[str, object]", properties["value"])["enum"])
    assert answer.request_state
    return key, answer.request_state, choices[0], params.message


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_patches(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        patch = _patches(graph)

        answer = await move_item(
            client, item=_ITEM, to_folder=_FOLDER, confirm=a_person_agrees(_modern_context())
        )

        _key, state, _agrees_with, message = _the_question(answer)
        assert state == write_state_for(mover.TOOL_NAME, DRIVE_ID, ITEM_ID, FOLDER_ID)
        assert message == "Move 'Budget.xlsx' from '/Reports' to '/Archive'?"
        assert patch.call_count == 0, "an unanswered question moved the item anyway"

    async def test_the_second_round_moves_under_the_answer_it_was_bound_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        patch = _patches(graph)
        key, state, agrees_with, _message = _the_question(
            await move_item(
                client, item=_ITEM, to_folder=_FOLDER, confirm=a_person_agrees(_modern_context())
            )
        )

        answer = await move_item(
            client,
            item=_ITEM,
            to_folder=_FOLDER,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": agrees_with})},
                    state=state,
                )
            ),
        )

        assert isinstance(answer, MovedItem)
        assert patch.call_count == 1, "the agreed move did not happen exactly once"

    async def test_an_answer_bound_to_another_destination_moves_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = graph.get(_OTHER_FOLDER_PATH).mock(
            return_value=httpx.Response(200, json=_folder_payload(folder_id=OTHER_FOLDER_ID))
        )
        patch = _patches(graph)
        key, state, agrees_with, _message = _the_question(
            await move_item(
                client, item=_ITEM, to_folder=_FOLDER, confirm=a_person_agrees(_modern_context())
            )
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await move_item(
                client,
                item=_ITEM,
                to_folder=_OTHER_FOLDER,
                confirm=a_person_agrees(
                    _modern_context(
                        answers={
                            key: ElicitResult(action="accept", content={"value": agrees_with})
                        },
                        state=state,
                    )
                ),
            )

        assert patch.call_count == 0, "the item moved under an answer given for another folder"

    async def test_a_decline_in_the_second_round_moves_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        patch = _patches(graph)
        key, state, _agrees_with, _message = _the_question(
            await move_item(
                client, item=_ITEM, to_folder=_FOLDER, confirm=a_person_agrees(_modern_context())
            )
        )

        with pytest.raises(ToolError, match=_NOTHING_MOVED):
            _ = await move_item(
                client,
                item=_ITEM,
                to_folder=_FOLDER,
                confirm=a_person_agrees(
                    _modern_context(answers={key: ElicitResult(action="decline")}, state=state)
                ),
            )

        assert patch.call_count == 0


class TestWhatItSendsToGraph:
    async def test_it_reads_the_item_and_the_folder_then_patches_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        item_route, folder_route = _reads(graph)
        patch = _patches(graph)

        _ = await _move(client)

        made = _made(graph)
        assert [call.request.method for call in made] == ["GET", "GET", "PATCH"]
        assert (item_route.call_count, folder_route.call_count, patch.call_count) == (1, 1, 1)
        assert made[2].request.url.path == f"/v1.0/drives/{DRIVE_ID}/items/{ITEM_ID}"

    async def test_the_patch_body_names_the_destination_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        patch = _patches(graph)

        _ = await _move(client)

        body = _sent(patch)
        assert body["parentReference"] == {"id": FOLDER_ID}
        assert set(body) <= {"@odata.type", "parentReference"}, f"the move also sent {body}"
        assert patch.calls.last.request.headers["content-type"] == "application/json"

    async def test_a_move_to_the_top_folder_sends_the_real_root_id_and_never_root(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(
            graph,
            folder=_folder_payload(folder_id=ROOT_ID, name="root", root=True),
            folder_path=_ROOT_ALIAS_PATH,
        )
        patch = _patches(graph, httpx.Response(200, json=_moved_payload(into=ROOT_ID)))
        bound: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert question
            bound.append(about)
            return None

        _ = await _move(client, to_folder=_ROOT_BY_ALIAS, confirm=capturing)

        assert _sent(patch)["parentReference"] == {"id": ROOT_ID}
        assert bound == [write_state_for(mover.TOOL_NAME, DRIVE_ID, ITEM_ID, ROOT_ID)]

    async def test_both_reads_ask_for_the_item_fields_and_the_root_facet(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        item_route, folder_route = _reads(graph)
        _ = _patches(graph)

        _ = await _move(client)

        for route in (item_route, folder_route):
            selected = route.calls.last.request.url.params["$select"].split(",")
            assert {"id", "name", "folder", "parentReference", "root"} <= set(selected)

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_patch_graph_answers_503_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        patch = _patches(graph, httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _move(client)

        assert patch.call_count == 1


class TestWhatItRefusesBeforeGraph:
    @pytest.mark.parametrize(
        "value",
        [
            ITEM_ID,
            "Budget.xlsx",
            "https://contoso.sharepoint.invalid/sites/finance/Budget.xlsx",
            "/drive/root:/Reports/Budget.xlsx",
            "",
            "sharepoint:///files/",
            f"sharepoint:///files/{DRIVE_ID}",
            "sharepoint:///files/%20/01SYNTHETICFILE0000",
            "outlook:///messages/AAMkAGI2SYNTHETIC",
        ],
    )
    async def test_a_value_that_is_not_an_item_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError, match="sharepoint_move_item takes a file handle"):
            _ = await _move(client, item=value)

        assert len(graph.calls) == 0, "a refused handle moved nothing, and read nothing either"

    @pytest.mark.parametrize(
        "value",
        [
            _ITEM,
            FOLDER_ID,
            "Archive",
            "https://contoso.sharepoint.invalid/sites/finance/Archive",
            "sharepoint:///folders/",
            "sharepoint:///folders/b%21SYNTHETICDRIVE0000/%20",
        ],
    )
    async def test_a_value_that_is_not_a_folder_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError, match="sharepoint_move_item takes a folder handle"):
            _ = await _move(client, to_folder=value)

        assert len(graph.calls) == 0

    async def test_two_drives_are_refused_with_the_copy_then_delete_route(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        elsewhere = DriveFolderHandle(OTHER_DRIVE_ID, FOLDER_ID).uri

        with pytest.raises(ToolError, match="two different drives") as refused:
            _ = await _move(client, to_folder=elsewhere)

        assert "sharepoint_copy_item" in str(refused.value)
        assert "sharepoint_delete_item" in str(refused.value)
        assert len(graph.calls) == 0

    async def test_an_item_cannot_move_into_itself(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        folder = DriveFolderHandle(DRIVE_ID, FOLDER_ID).uri

        with pytest.raises(ToolError, match="cannot move into itself"):
            _ = await _move(client, item=folder, to_folder=folder)

        assert len(graph.calls) == 0


class TestWhatItRefusesAfterTheReads:
    async def test_the_top_folder_of_a_drive_is_never_moved_or_asked_about(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, item=_file_payload(root=True))
        patch = _patches(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> Confirmed:
            assert about
            asked.append(question)
            return None

        with pytest.raises(ToolError, match="top folder of a drive cannot move"):
            _ = await _move(client, confirm=counting)

        assert asked == []
        assert patch.call_count == 0

    async def test_a_destination_that_is_not_a_folder_is_never_moved_into(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, folder=_folder_payload(a_folder=False))
        patch = _patches(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> Confirmed:
            assert about
            asked.append(question)
            return None

        with pytest.raises(ToolError, match="does not hold as a folder"):
            _ = await _move(client, confirm=counting)

        assert asked == []
        assert patch.call_count == 0

    async def test_a_move_into_the_folder_that_holds_the_item_is_never_asked_or_sent(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, item=_file_payload(parent_id=FOLDER_ID))
        patch = _patches(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> Confirmed:
            assert about
            asked.append(question)
            return None

        with pytest.raises(ToolError, match="already in the folder") as refused:
            _ = await _move(client, confirm=counting)

        assert str(refused.value).startswith(_NOTHING_MOVED)
        assert asked == []
        assert patch.call_count == 0

    async def test_the_top_folder_by_its_alias_is_the_folder_that_holds_a_top_level_item(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(
            graph,
            item=_file_payload(parent_id=ROOT_ID, parent_path="/drive/root:"),
            folder=_folder_payload(folder_id=ROOT_ID, name="root", root=True),
            folder_path=_ROOT_ALIAS_PATH,
        )
        patch = _patches(graph)

        with pytest.raises(ToolError, match="already in the folder"):
            _ = await _move(client, to_folder=_ROOT_BY_ALIAS)

        assert patch.call_count == 0


class TestWhatItAnswers:
    async def test_the_answer_is_the_item_as_graph_holds_it_after_the_move(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _patches(graph)

        answer = await _move(client)

        assert answer.item.uri == _ITEM
        assert answer.item.name == _NAME
        assert answer.item.parent_uri == _FOLDER
        assert answer.item.parent_path == "/drive/root:/Archive"

    async def test_the_previous_parent_is_the_folder_the_pre_read_named(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _patches(graph)

        answer = await _move(client)

        assert answer.previous_parent_uri == DriveFolderHandle(DRIVE_ID, OLD_PARENT_ID).uri

    async def test_the_previous_parent_is_null_when_graph_named_no_parent_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, item=_file_payload(parent_id=None))
        _ = _patches(graph)

        answer = await _move(client)

        assert answer.previous_parent_uri is None

    @pytest.mark.parametrize(
        "response",
        [httpx.Response(200, json={}), httpx.Response(204)],
        ids=["empty-item", "no-content"],
    )
    async def test_a_move_answered_without_the_item_reads_the_item_again(
        self, client: GraphServiceClient, graph: respx.MockRouter, response: httpx.Response
    ) -> None:
        item_route = graph.get(_ITEM_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_file_payload()),
                httpx.Response(200, json=_moved_payload()),
            ]
        )
        _ = graph.get(_FOLDER_PATH).mock(return_value=httpx.Response(200, json=_folder_payload()))
        patch = _patches(graph, response)

        answer = await _move(client)

        assert answer.item.parent_uri == _FOLDER
        assert patch.call_count == 1
        assert item_route.call_count == 2, "the pre-read and the read after the move"

    async def test_a_failed_read_after_the_move_says_that_the_item_moved(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_file_payload()),
                httpx.Response(404, json=_NOT_FOUND),
            ]
        )
        _ = graph.get(_FOLDER_PATH).mock(return_value=httpx.Response(200, json=_folder_payload()))
        patch = _patches(graph, httpx.Response(204))

        with pytest.raises(Advised, match="Microsoft 365 moved the item") as raised:
            _ = await _move(client)

        assert isinstance(raised.value.__cause__, GraphNotFound)
        assert patch.call_count == 1

    async def test_a_read_after_the_move_with_no_drive_says_that_the_item_moved(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_file_payload()),
                httpx.Response(
                    200, json={**_moved_payload(), "parentReference": {"id": FOLDER_ID}}
                ),
            ]
        )
        _ = graph.get(_FOLDER_PATH).mock(return_value=httpx.Response(200, json=_folder_payload()))
        patch = _patches(graph, httpx.Response(204))

        with pytest.raises(Advised, match="Microsoft 365 moved the item") as raised:
            _ = await _move(client)

        assert "makes no second change" in str(raised.value)
        assert patch.call_count == 1


class TestGraphFailures:
    async def test_a_404_on_the_item_read_is_a_not_found_and_nothing_is_patched(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(return_value=httpx.Response(404, json=_NOT_FOUND))
        patch = _patches(graph)

        with pytest.raises(GraphNotFound):
            _ = await _move(client)

        assert patch.call_count == 0

    async def test_a_404_on_the_folder_read_is_a_not_found_and_nothing_is_patched(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(return_value=httpx.Response(200, json=_file_payload()))
        _ = graph.get(_FOLDER_PATH).mock(return_value=httpx.Response(404, json=_NOT_FOUND))
        patch = _patches(graph)

        with pytest.raises(GraphNotFound):
            _ = await _move(client)

        assert patch.call_count == 0

    async def test_a_name_clash_in_the_destination_is_passed_on_as_a_409(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _patches(graph, httpx.Response(409, json=_NAME_EXISTS))

        with pytest.raises(GraphFailure) as raised:
            _ = await _move(client)

        assert raised.value.status == 409

    async def test_a_name_clash_reaches_the_client_as_the_name_conflict_advice(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        patch = _patches(graph, httpx.Response(409, json=_NAME_EXISTS))

        advice = await _advised(client)

        assert "an item at that level already has the same name" in advice
        assert "HTTP 409" in advice
        assert mover.GRAPH_NOT_FOUND not in advice
        assert patch.call_count == 1

    @pytest.mark.parametrize("path", [_ITEM_PATH, _FOLDER_PATH], ids=["item", "folder"])
    async def test_a_404_on_a_read_reaches_the_client_as_this_tools_not_found_advice(
        self, client: GraphServiceClient, graph: respx.MockRouter, path: str
    ) -> None:
        _ = _reads(graph)
        _ = graph.get(path).mock(return_value=httpx.Response(404, json=_NOT_FOUND))
        patch = _patches(graph)

        advice = await _advised(client)

        assert advice.startswith(mover.GRAPH_NOT_FOUND)
        assert patch.call_count == 0

    async def test_a_404_on_the_patch_reaches_the_client_as_this_tools_not_found_advice(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _patches(graph, httpx.Response(404, json=_NOT_FOUND))

        advice = await _advised(client)

        assert advice.startswith(mover.GRAPH_NOT_FOUND)

    async def test_the_call_example_reaches_graph_and_the_pre_read_is_what_a_403_refuses(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        example = cast("Mapping[str, str]", mover.GRAPH_CALL_EXAMPLE)
        refused = graph.get(_ITEM_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _move(client, item=example["item"], to_folder=example["to_folder"])

        assert refused.call_count == 1


class _StubOboCredential:
    async def get_token(self, *scopes: str) -> GraphAccessToken:
        _ = scopes
        return GraphAccessToken(token=_OBO_TOKEN, expires_on=0)


@pytest.fixture
def obo(monkeypatch: pytest.MonkeyPatch) -> None:
    credential = _StubOboCredential()

    async def get_obo_credential(
        _self: AzureProvider, *, user_assertion: str
    ) -> _StubOboCredential:
        assert user_assertion == _CLIENT_TOKEN, "the client's own token is what gets exchanged"
        return credential

    monkeypatch.setattr(AzureProvider, "get_obo_credential", get_obo_credential)
    monkeypatch.setattr(
        "fastmcp.server.dependencies.get_access_token",
        lambda: AccessToken(token=_CLIENT_TOKEN, client_id=_CLIENT_ID, scopes=["access_as_user"]),
    )


@pytest.fixture
def drive() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=GRAPH_V1, assert_all_called=False) as router:
        _ = router.get(_ITEM_PATH).mock(return_value=httpx.Response(200, json=_file_payload()))
        _ = router.get(_FOLDER_PATH).mock(return_value=httpx.Response(200, json=_folder_payload()))
        _ = router.patch(_ITEM_PATH).mock(return_value=httpx.Response(200, json=_moved_payload()))
        yield router


@pytest.fixture
async def app() -> AsyncIterator[Starlette]:
    composed = create_app(
        config=AppConfig.model_validate({"public_base_url": "https://office-365-mcp.example"}),
        database_config=DatabaseConfig.model_validate(
            {"url": "postgresql://user:pass@127.0.0.1:1/nope"}
        ),
        entra_config=EntraConfig.model_validate(
            {
                "tenant_id": "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81",
                "client_id": _CLIENT_ID,
                "client_secret": "s3cr3t",
            }
        ),
        surface_config=SurfaceConfig.model_validate({"tools_enabled": "sharepoint_read_file"}),
    )
    transport = create_graph_transport(GraphSettings())
    mover.register(cast("FastMCP[None]", composed.state.fastmcp_server), transport)
    yield composed
    await transport.aclose()


async def _agree(
    _message: str, _response_type: type | None, params: ElicitRequestParams, _context: object
) -> ClientAnswer[dict[str, str]]:
    assert isinstance(params, ElicitRequestFormParams)
    choices = cast("list[str]", params.requested_schema["properties"]["value"]["enum"])
    return ClientAnswer(action="accept", content={"value": choices[0]})


async def _decline(
    _message: str, _response_type: type | None, _params: ElicitRequestParams, _context: object
) -> ClientAnswer[str]:
    return ClientAnswer(action="decline")


def _patched(router: respx.MockRouter) -> list[str]:
    return [call.request.url.path for call in _made(router) if call.request.method == "PATCH"]


@pytest.mark.usefixtures("obo")
class TestTheWholeConfirmationOverARealClient:
    async def test_the_call_example_moves_the_item_once_for_an_agreeing_client(
        self, app: Starlette, drive: respx.MockRouter
    ) -> None:
        server = cast("FastMCP[None]", app.state.fastmcp_server)
        async with Client(FastMCPTransport(server), elicitation_handler=_agree) as agreeing:
            assert agreeing.protocol_version == LATEST_MODERN_VERSION
            result = await agreeing.call_tool(mover.TOOL_NAME, dict(mover.GRAPH_CALL_EXAMPLE))

        answer = cast("Mapping[str, object] | None", result.structured_content)
        assert answer is not None, "the agreed move answered nothing"
        assert set(MovedItem.model_fields) <= set(answer)
        assert _patched(drive) == [f"/v1.0/drives/{DRIVE_ID}/items/{ITEM_ID}"]

    async def test_a_person_who_says_no_leaves_the_item_where_it_is(
        self, app: Starlette, drive: respx.MockRouter
    ) -> None:
        server = cast("FastMCP[None]", app.state.fastmcp_server)
        async with Client(FastMCPTransport(server), elicitation_handler=_decline) as declining:
            with pytest.raises(ToolError, match="did not agree"):
                _ = await declining.call_tool(mover.TOOL_NAME, dict(mover.GRAPH_CALL_EXAMPLE))

        assert _patched(drive) == []
        assert {call.request.method for call in _made(drive)} == {"GET"}


class TestHowItDeclaresItself:
    def test_the_permission_is_files_readwrite_all(self) -> None:
        assert mover.GRAPH_PERMISSIONS == ("Files.ReadWrite.All",)

    def test_its_step_is_the_move(self) -> None:
        assert mover.STEP_MOVE == "move_item"

    def test_the_call_example_is_an_item_and_a_folder_in_one_drive(self) -> None:
        example = cast("Mapping[str, str]", mover.GRAPH_CALL_EXAMPLE)
        item = drive_item_handle(example["item"])
        folder = drive_folder_handle(example["to_folder"])

        assert item is not None and folder is not None
        assert item.drive_id == folder.drive_id
        assert item.item_id != folder.item_id

    async def test_it_takes_two_arguments_and_no_others(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"item", "to_folder"} == set(mover.GRAPH_CALL_EXAMPLE)
        assert set(cast("Sequence[str]", parameters["required"])) == {"item", "to_folder"}

    @pytest.mark.parametrize("word", ["client", "ctx", "context", "token", "graph"])
    async def test_no_wiring_of_this_server_is_published_as_an_argument(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_it_announces_itself_as_a_destructive_write_that_is_safe_to_repeat(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert tool.title == "Move an Item"
        assert annotations.read_only_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["idempotentHint"]

    def test_it_names_no_tool_that_shows_the_change(self) -> None:
        assert not hasattr(mover, "CHANGE_SHOWN_BY")

    @pytest.mark.parametrize(
        "sentence",
        [
            "This tool asks the user to agree before it changes anything, every time.",
            "OneDrive and SharePoint can show the change to everyone who can open the folder.",
            "This tool moves an item inside one drive only.",
            "use sharepoint_copy_item. Then use sharepoint_delete_item on the original.",
            "This call is safe to repeat after a timeout.",
            "To change the name, use sharepoint_rename_item.",
            "Get both handles from sharepoint_search_files or sharepoint_browse_folder.",
        ],
    )
    async def test_the_description_says(self, transport: httpx.AsyncClient, sentence: str) -> None:
        _parameters, tool = await _registered(transport)

        assert sentence in " ".join((tool.description or "").split())

    async def test_the_lead_paragraph_ends_with_who_can_see_the_change(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        lead = " ".join((tool.description or "").split("\n\nNotes:")[0].split())
        assert lead.endswith(
            "OneDrive and SharePoint can show the change to everyone who can open the folder."
        )

    @pytest.mark.parametrize(
        "phrase", ["across drives", "between drives", "any drive", "no question", "erase"]
    )
    async def test_the_description_promises_no_move_between_drives_and_no_skipped_question(
        self, transport: httpx.AsyncClient, phrase: str
    ) -> None:
        _parameters, tool = await _registered(transport)

        assert phrase not in (tool.description or "").casefold()

    @pytest.mark.parametrize("argument", ["item", "to_folder"])
    async def test_each_argument_is_described_in_15_to_60_words(
        self, transport: httpx.AsyncClient, argument: str
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])
        description = str(properties[argument].get("description", ""))
        assert 15 <= len(description.split()) <= 60

    async def test_the_destination_argument_names_where_a_top_folder_handle_comes_from(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])
        description = str(properties["to_folder"].get("description", ""))
        assert "`root_uri`" in description
        assert "sharepoint_list_drives" in description

    async def test_the_description_keeps_the_house_shape(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "\n\nNotes:\n- " in description
        assert 45 <= len(description.split()) <= 210

    @pytest.mark.parametrize("field", sorted(MovedItem.model_fields))
    def test_every_answer_field_is_described_in_15_to_60_words(self, field: str) -> None:
        description = MovedItem.model_fields[field].description or ""

        assert 15 <= len(description.split()) <= 60

    def test_not_found_advice_points_at_the_tools_that_find_the_item_again(self) -> None:
        assert "sharepoint_search_files" in mover.GRAPH_NOT_FOUND
        assert "sharepoint_browse_folder" in mover.GRAPH_NOT_FOUND
        assert "nothing was moved" in mover.GRAPH_NOT_FOUND
