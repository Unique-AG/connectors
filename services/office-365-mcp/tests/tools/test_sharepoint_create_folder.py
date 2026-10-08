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

from office_365_mcp.graph_client import (
    GraphFailure,
    GraphForbidden,
    GraphNotFound,
    GraphUnavailable,
)
from office_365_mcp.shared.files import FOLDER_HANDLE_SOURCES, NAME_RULES, DriveItemSummary
from office_365_mcp.shared.handles import (
    DriveFileHandle,
    DriveFolderHandle,
    OnenoteSectionHandle,
    drive_folder_handle,
)
from office_365_mcp.shared.notes import write_state_for
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Advised,
    Confirm,
    Confirmed,
    GraphAdviceMiddleware,
)
from office_365_mcp.tools import graph_advice, resolve
from office_365_mcp.tools import sharepoint_create_folder as creator
from office_365_mcp.tools.sharepoint_create_folder import a_person_agrees, create_folder

_DRIVE_ID = "b!SYNTHETICDRIVE0000"
_PARENT_ID = "01SYNTHETICFOLDER000"
_NEW_ID = "01SYNTHETICNEWFOLDER0"
_ROOT_ID = "01SYNTHETICROOT00000"

_PARENT_URI = DriveFolderHandle(_DRIVE_ID, _PARENT_ID).uri

_DRIVE_PATH = "/drives/b%21SYNTHETICDRIVE0000"
_PARENT_PATH = f"{_DRIVE_PATH}/items/{_PARENT_ID}"
_CHILDREN_PATH = f"{_PARENT_PATH}/children"
_NEW_PATH = f"{_DRIVE_PATH}/items/{_NEW_ID}"

_NAME = "Q3"

_NOTHING_CREATED = "No folder was created."

_CONFLICT_BEHAVIOR = "@microsoft.graph.conflictBehavior"


def _parent_payload(
    *,
    item_id: str = _PARENT_ID,
    name: str | None = "Reports",
    path: str | None = "/drive/root:/Finance%20Team",
    folder: bool = True,
    root: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": item_id,
        "name": name,
        "parentReference": {"driveId": _DRIVE_ID, "id": "01SYNTHETICGRANDPA00", "path": path},
    }
    if folder:
        payload["folder"] = {"childCount": 2}
    else:
        payload["file"] = {"mimeType": "text/plain"}
    if root:
        payload["root"] = {}
    return payload


def _created_payload(
    *, item_id: str | None = _NEW_ID, drive_id: str | None = _DRIVE_ID, name: str = _NAME
) -> dict[str, object]:
    payload: dict[str, object] = {"name": name, "folder": {"childCount": 0}, "size": 0}
    if item_id is not None:
        payload["id"] = item_id
    if drive_id is not None:
        payload["parentReference"] = {
            "driveId": drive_id,
            "id": _PARENT_ID,
            "path": "/drive/root:/Finance%20Team/Reports",
        }
    return payload


def _reads(
    graph: respx.MockRouter,
    payload: Mapping[str, object] | None = None,
    *,
    path: str = _PARENT_PATH,
) -> respx.Route:
    body = dict(payload) if payload is not None else _parent_payload()
    return graph.get(path).mock(return_value=httpx.Response(200, json=body))


def _creates(
    graph: respx.MockRouter,
    payload: Mapping[str, object] | None = None,
    *,
    path: str = _CHILDREN_PATH,
) -> respx.Route:
    body = dict(payload) if payload is not None else _created_payload()
    return graph.post(path).mock(return_value=httpx.Response(201, json=body))


async def _agrees(question: str, about: str) -> Confirmed:
    assert question, "the person was asked nothing at all"
    assert about, "the answer was bound to nothing"
    return None


async def _refuses(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOTHING_CREATED


async def _create(
    client: GraphServiceClient,
    *,
    parent: str = _PARENT_URI,
    name: str = _NAME,
    confirm: Confirm = _agrees,
) -> DriveItemSummary:
    answer = await create_folder(client, parent=parent, name=name, confirm=confirm)
    assert isinstance(answer, DriveItemSummary), "this call was answered with a question"
    return answer


async def _advised_create(client: GraphServiceClient) -> str:
    async def creating(context: MiddlewareContext[CallToolRequestParams]) -> ToolResult:
        assert context.message.name == creator.TOOL_NAME
        _ = await _create(client)
        raise AssertionError("Graph refused the create, and the call still answered")

    middleware = GraphAdviceMiddleware(
        graph_advice(resolve(preset=None, enabled=(creator.TOOL_NAME,)))
    )
    context = MiddlewareContext(message=CallToolRequestParams(name=creator.TOOL_NAME, arguments={}))
    with pytest.raises(ToolError) as raised:
        _ = await middleware.on_call_tool(context, creating)
    return str(raised.value)


def _made(route: respx.Route) -> Sequence[Call]:
    return cast("Sequence[Call]", route.calls)


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    creator.register(mcp, transport)
    tool = await mcp.get_tool(creator.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestWhatItSendsToGraph:
    async def test_it_reads_the_parent_then_creates_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph)
        post = _creates(graph)

        _ = await _create(client)

        assert read.call_count == 1
        assert post.call_count == 1
        made = cast("Sequence[Call]", graph.calls)
        assert [call.request.method for call in made] == ["GET", "POST"]

    async def test_the_create_goes_to_the_children_of_the_id_graph_returned(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(
            graph,
            _parent_payload(item_id=_ROOT_ID, name="root", path=None, root=True),
            path=f"{_DRIVE_PATH}/items/root",
        )
        post = _creates(graph, path=f"{_DRIVE_PATH}/items/{_ROOT_ID}/children")

        _ = await _create(client, parent=DriveFolderHandle(_DRIVE_ID, "root").uri)

        assert post.call_count == 1, "the create used the alias instead of the id Graph returned"

    async def test_the_url_asks_graph_to_fail_on_a_name_that_is_already_there(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        post = _creates(graph)

        _ = await _create(client)

        assert _made(post)[0].request.url.params[_CONFLICT_BEHAVIOR] == "fail"

    async def test_the_body_carries_the_name_and_the_folder_facet_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        post = _creates(graph)

        _ = await _create(client)

        body = cast("Mapping[str, object]", json.loads(_made(post)[0].request.content))
        assert body["name"] == _NAME
        assert body["folder"] == {}
        assert set(body) <= {"@odata.type", "name", "folder"}

    async def test_the_parent_is_read_with_the_fields_the_question_needs(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph)
        _ = _creates(graph)

        _ = await _create(client)

        selected = _made(read)[0].request.url.params["$select"].split(",")
        assert {"name", "folder", "parentReference", "root"} <= set(selected)


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_create_graph_answers_503_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        post = graph.post(_CHILDREN_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _create(client)

        assert post.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_throttled_create_is_not_repeated_either(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        post = graph.post(_CHILDREN_PATH).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "12"})
        )

        with pytest.raises(GraphFailure):
            _ = await _create(client)

        assert post.call_count == 1


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            DriveFileHandle(_DRIVE_ID, _PARENT_ID).uri,
            OnenoteSectionHandle("SECTION1").uri,
            _PARENT_ID,
            _DRIVE_ID,
            "Reports",
            "/drive/root:/Finance/Reports",
            "https://contoso.sharepoint.invalid/sites/finance/Shared%20Documents/Reports",
            "",
            "   ",
            "sharepoint:///folders/",
            "sharepoint:///folders/%20/01SYNTHETICFOLDER000",
            "sharepoint:///folders/b%21SYNTHETICDRIVE0000/",
        ],
    )
    async def test_a_value_that_is_not_a_folder_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError):
            _ = await _create(client, parent=value)

        assert len(graph.calls) == 0, "a refused handle creates nothing"

    async def test_the_refusal_shows_the_shape_and_names_every_tool_that_mints_a_folder(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await _create(client, parent="Reports")

        message = str(refused.value)
        assert "sharepoint:///folders/{drive_id}/{item_id}" in message
        for tool in (
            "sharepoint_browse_folder",
            "sharepoint_search_files",
            "sharepoint_list_drives",
            "sharepoint_resolve_url",
        ):
            assert tool in message
        assert "`root_uri` of a drive" in message
        assert FOLDER_HANDLE_SOURCES in message
        assert "do not retry it" in message

    async def test_a_file_handle_is_refused_by_name(self, client: GraphServiceClient) -> None:
        with pytest.raises(ToolError, match="A file handle"):
            _ = await _create(client, parent=DriveFileHandle(_DRIVE_ID, _PARENT_ID).uri)

    @pytest.mark.parametrize("name", ["Q1/Q2", "Q1:Q2", 'Q1"Q2', "~$draft", " "])
    async def test_a_name_microsoft_does_not_allow_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, name: str
    ) -> None:
        with pytest.raises(ToolError, match="does not allow this name"):
            _ = await _create(client, name=name)

        assert len(graph.calls) == 0

    @pytest.mark.parametrize("name", ["Q3 #1", "50%", "~draft", "Reports."])
    async def test_a_name_microsoft_can_accept_reaches_the_create(
        self, client: GraphServiceClient, graph: respx.MockRouter, name: str
    ) -> None:
        _ = _reads(graph)
        post = _creates(graph, _created_payload(name=name))

        _ = await _create(client, name=name)

        body = cast("Mapping[str, object]", json.loads(_made(post)[0].request.content))
        assert body["name"] == name

    async def test_an_item_that_is_not_a_folder_is_refused_before_anything_is_asked(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph, _parent_payload(name="notes.txt", folder=False))
        post = _creates(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert about
            asked.append(question)
            return None

        with pytest.raises(ToolError, match="is not a folder"):
            _ = await _create(client, confirm=capturing)

        assert read.call_count == 1
        assert post.call_count == 0
        assert asked == []


class TestWhatItAnswers:
    async def test_the_answer_is_the_new_folder_with_handles_that_reach_it_again(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _creates(graph)

        answer = await _create(client)

        assert answer.uri == DriveFolderHandle(_DRIVE_ID, _NEW_ID).uri
        assert answer.parent_uri == _PARENT_URI
        assert answer.is_folder is True
        assert answer.name == _NAME
        assert answer.child_count == 0

    async def test_the_answer_reports_the_name_microsoft_stored(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _creates(graph, _created_payload(name="Q3 (stored)"))

        answer = await _create(client)

        assert answer.name == "Q3 (stored)"

    async def test_a_create_answer_with_no_drive_is_read_again_by_the_new_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        post = _creates(graph, _created_payload(drive_id=None))
        reread = graph.get(_NEW_PATH).mock(
            return_value=httpx.Response(200, json=_created_payload())
        )

        answer = await _create(client)

        assert post.call_count == 1
        assert reread.call_count == 1
        assert answer.uri == DriveFolderHandle(_DRIVE_ID, _NEW_ID).uri
        assert answer.parent_uri == _PARENT_URI

    async def test_a_failed_second_read_says_that_the_folder_was_created(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        post = _creates(graph, _created_payload(drive_id=None))
        _ = graph.get(_NEW_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(Advised, match="Microsoft 365 created the folder") as advised:
            _ = await _create(client)

        assert isinstance(advised.value.__cause__, GraphFailure)
        assert "Do not call sharepoint_create_folder again" in str(advised.value)
        assert "sharepoint_browse_folder" in str(advised.value)
        assert post.call_count == 1

    async def test_a_create_answer_with_no_id_says_that_the_folder_was_created_and_reads_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        post = _creates(graph, _created_payload(item_id=None))

        with pytest.raises(Advised, match="Microsoft 365 created the folder") as advised:
            _ = await _create(client)

        assert "Do not call sharepoint_create_folder again" in str(advised.value)
        assert "sharepoint_browse_folder" in str(advised.value)
        assert post.call_count == 1
        assert len(graph.calls) == 2, "the create was followed by another call"


class TestTheFailuresItPassesOn:
    async def test_a_name_that_is_already_there_reaches_the_caller_as_a_409(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        post = graph.post(_CHILDREN_PATH).mock(
            return_value=httpx.Response(
                409,
                json={"error": {"code": "nameAlreadyExists", "message": "Name already exists"}},
            )
        )

        with pytest.raises(GraphFailure) as failed:
            _ = await _create(client)

        assert failed.value.status == 409
        assert failed.value.code == "nameAlreadyExists"
        assert post.call_count == 1

    async def test_a_404_on_the_pre_read_is_a_not_found_and_nothing_is_created(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = graph.get(_PARENT_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )
        post = _creates(graph)

        with pytest.raises(GraphNotFound):
            _ = await _create(client)

        assert read.call_count == 1
        assert post.call_count == 0

    async def test_a_refused_create_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = graph.post(_CHILDREN_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _create(client)

    async def test_a_403_on_the_create_after_the_read_reaches_the_model_as_item_access(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        post = graph.post(_CHILDREN_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        message = await _advised_create(client)

        assert message.startswith(creator.GRAPH_FORBIDDEN)
        assert "HTTP 403" in message
        assert "administrator to grant" not in message
        assert "Files.ReadWrite.All" not in message
        assert post.call_count == 1


class TestThePersonBeforeTheCreate:
    async def test_a_refusal_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph)
        post = _creates(graph)

        with pytest.raises(ToolError, match=_NOTHING_CREATED):
            _ = await create_folder(client, parent=_PARENT_URI, name=_NAME, confirm=_refuses)

        assert read.call_count == 1
        assert post.call_count == 0, "a declined create still reached the drive"

    async def test_the_question_carries_the_name_and_the_destination(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _creates(graph)
        asked: list[str] = []
        bound: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            asked.append(question)
            bound.append(about)
            return None

        _ = await _create(client, confirm=capturing)

        assert asked == ["Create the folder 'Q3' inside the folder '/Finance Team/Reports'?"]
        assert bound == [write_state_for(creator.TOOL_NAME, _DRIVE_ID, _PARENT_ID, _NAME)]

    async def test_the_question_shows_no_part_of_the_graph_path_prefix(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _creates(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, confirm=capturing)

        assert asked
        assert "/drive/" not in asked[0]
        assert "root:" not in asked[0]

    async def test_the_question_names_a_parent_with_no_parent_path_by_its_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _parent_payload(path=None))
        _ = _creates(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, confirm=capturing)

        assert asked == ["Create the folder 'Q3' inside the folder 'Reports'?"]

    async def test_the_question_names_the_top_of_the_drive_for_a_drive_root(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _parent_payload(name="root", path=None, root=True))
        _ = _creates(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, confirm=capturing)

        assert asked == ["Create the folder 'Q3' inside the top folder of the drive?"]

    async def test_the_question_names_no_folder_graph_left_unnamed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _parent_payload(name=None, path=None))
        _ = _creates(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, confirm=capturing)

        assert asked == ["Create the folder 'Q3' inside an unnamed folder?"]

    async def test_the_person_is_asked_after_the_read_and_before_the_create(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _creates(graph)
        seen: list[list[str]] = []

        async def recording(question: str, about: str) -> Confirmed:
            assert question and about
            seen.append([call.request.method for call in cast("Sequence[Call]", graph.calls)])
            return None

        _ = await _create(client, confirm=recording)

        assert seen == [["GET"]]

    def test_the_binding_differs_for_another_name_or_another_parent_or_another_drive(
        self,
    ) -> None:
        bound = write_state_for(creator.TOOL_NAME, _DRIVE_ID, _PARENT_ID, _NAME)

        assert bound != write_state_for(creator.TOOL_NAME, _DRIVE_ID, _PARENT_ID, "Q4")
        assert bound != write_state_for(creator.TOOL_NAME, _DRIVE_ID, "01SYNTHETICOTHER0000", _NAME)
        assert bound != write_state_for(creator.TOOL_NAME, "b!SYNTHETICOTHER00", _PARENT_ID, _NAME)

    @pytest.mark.parametrize(
        "answer",
        [
            DeclinedElicitation(),
            CancelledElicitation(),
            AcceptedElicitation(data="do not create"),
            MCPError(METHOD_NOT_FOUND, "Method not found"),
            ToolError("the client refused the request"),
        ],
        ids=["declined", "cancelled", "another-answer", "cannot-ask", "client-error"],
    )
    async def test_no_refusal_is_ever_raised(self, answer: object) -> None:
        confirm = a_person_agrees(_context(answer))

        refusal = await confirm("Create the folder 'Q3' inside the folder 'Reports'?", "state")

        assert isinstance(refusal, str)
        assert refusal

    async def test_a_refusal_this_tool_words_opens_by_saying_no_folder_was_created(self) -> None:
        confirm = a_person_agrees(_context(DeclinedElicitation()))

        refusal = await confirm("Create the folder 'Q3' inside the folder 'Reports'?", "state")

        assert isinstance(refusal, str)
        assert refusal.startswith(_NOTHING_CREATED)

    async def test_agreeing_answers_with_no_refusal(self) -> None:
        confirm = a_person_agrees(_context(AcceptedElicitation(data="create")))

        assert await confirm("Create the folder 'Q3'?", "state") is None


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
    async def test_the_first_round_asks_and_never_reaches_the_create(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        post = _creates(graph)

        answer = await create_folder(
            client, parent=_PARENT_URI, name=_NAME, confirm=a_person_agrees(_modern_context())
        )

        assert isinstance(answer, InputRequiredResult)
        assert answer.request_state == write_state_for(
            creator.TOOL_NAME, _DRIVE_ID, _PARENT_ID, _NAME
        )
        assert post.call_count == 0

    async def test_the_first_round_asks_the_question_this_tool_words(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _creates(graph)

        answer = await create_folder(
            client, parent=_PARENT_URI, name=_NAME, confirm=a_person_agrees(_modern_context())
        )

        assert isinstance(answer, InputRequiredResult)
        requests = answer.input_requests or {}
        request = requests[next(iter(requests))]
        assert isinstance(request, ElicitRequest)
        params = request.params
        assert isinstance(params, ElicitRequestFormParams)
        assert "'Q3'" in params.message
        assert "'/Finance Team/Reports'" in params.message

    async def test_the_second_round_creates_the_folder_the_answer_was_bound_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        post = _creates(graph)

        first = await create_folder(
            client, parent=_PARENT_URI, name=_NAME, confirm=a_person_agrees(_modern_context())
        )
        assert isinstance(first, InputRequiredResult)
        key = next(iter(first.input_requests or {}))

        answer = await create_folder(
            client,
            parent=_PARENT_URI,
            name=_NAME,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": "create"})},
                    state=first.request_state,
                )
            ),
        )

        assert isinstance(answer, DriveItemSummary)
        assert post.call_count == 1
        body = cast("Mapping[str, object]", json.loads(_made(post)[0].request.content))
        assert body["name"] == _NAME

    async def test_an_answer_bound_to_another_name_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        post = _creates(graph)

        first = await create_folder(
            client, parent=_PARENT_URI, name=_NAME, confirm=a_person_agrees(_modern_context())
        )
        assert isinstance(first, InputRequiredResult)
        key = next(iter(first.input_requests or {}))

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await create_folder(
                client,
                parent=_PARENT_URI,
                name="Q4",
                confirm=a_person_agrees(
                    _modern_context(
                        answers={key: ElicitResult(action="accept", content={"value": "create"})},
                        state=first.request_state,
                    )
                ),
            )

        assert post.call_count == 0, "folder Q4 was created on an accept given for folder Q3"


class TestTheClientThatCannotAsk:
    async def test_a_client_that_cannot_ask_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        post = _creates(graph)
        confirm = a_person_agrees(_context(MCPError(METHOD_NOT_FOUND, "Method not found")))

        with pytest.raises(ToolError, match="does not support elicitation"):
            _ = await create_folder(client, parent=_PARENT_URI, name=_NAME, confirm=confirm)

        assert post.call_count == 0


class TestHowItDeclaresItself:
    def test_the_permission_is_files_readwrite_all(self) -> None:
        assert creator.GRAPH_PERMISSIONS == ("Files.ReadWrite.All",)

    def test_its_write_step_is_create_folder(self) -> None:
        assert creator.STEP_CREATE_FOLDER == "create_folder"

    def test_the_change_is_shown_by_sharepoint_browse_folder(self) -> None:
        assert creator.CHANGE_SHOWN_BY == ("sharepoint_browse_folder",)

    async def test_the_call_example_reaches_graph_with_an_agreeing_client(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        example = cast("Mapping[str, str]", creator.GRAPH_CALL_EXAMPLE)
        handle = drive_folder_handle(example["parent"])
        assert handle is not None, "GRAPH_CALL_EXAMPLE's own parent value is not a folder handle"
        read = _reads(graph, _parent_payload(item_id=handle.item_id))
        post = _creates(graph)

        _ = await _create(client, parent=example["parent"], name=example["name"])

        assert read.call_count == 1
        assert post.call_count == 1

    async def test_the_two_arguments_are_parent_and_name_and_nothing_else(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"parent", "name"}
        assert set(cast("Sequence[str]", parameters["required"])) == {"parent", "name"}
        assert set(creator.GRAPH_CALL_EXAMPLE) == set(properties)

    async def test_the_parent_description_names_every_tool_that_mints_a_folder(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])
        described = cast("str", properties["parent"]["description"])
        for tool in (
            "sharepoint_browse_folder",
            "sharepoint_search_files",
            "sharepoint_list_drives",
            "sharepoint_resolve_url",
        ):
            assert tool in described
        assert "`root_uri` of a drive" in described
        assert FOLDER_HANDLE_SOURCES in described

    async def test_the_parent_argument_is_described_in_15_to_60_words(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])
        assert 15 <= len(cast("str", properties["parent"]["description"]).split()) <= 60

    async def test_the_name_description_states_the_name_rules(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])
        assert NAME_RULES in cast("str", properties["name"]["description"])

    @pytest.mark.parametrize("word", ["client", "ctx", "context", "token", "graph"])
    async def test_no_wiring_of_this_server_is_published_as_an_argument(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_it_announces_itself_as_an_addition_rather_than_a_destructive_write(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_ADDITIVE["idempotentHint"]
        assert annotations.open_world_hint is WRITE_ADDITIVE["openWorldHint"]
        assert tool.title == "Create a Folder"

    async def test_the_answer_is_one_drive_item_object(self, transport: httpx.AsyncClient) -> None:
        _parameters, tool = await _registered(transport)

        schema = cast("Mapping[str, object]", tool.output_schema)
        assert schema["type"] == "object"
        assert {"uri", "parent_uri", "is_folder", "name"} <= set(
            cast("Mapping[str, object]", schema["properties"])
        )

    async def test_the_description_says_it_always_asks(self, transport: httpx.AsyncClient) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "This tool asks the user to agree before it creates anything, every time." in (
            description
        )
        assert "without a question" not in description

    async def test_the_lead_paragraph_ends_by_saying_who_can_see_the_change(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        lead, _notes = (tool.description or "").split("\n\nNotes:\n")
        assert lead.endswith(
            "OneDrive and SharePoint can show the change to everyone who can open the folder."
        )

    async def test_the_description_says_a_name_that_is_there_creates_nothing(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert (
            "If a folder named `name` is already there, Microsoft refuses and creates nothing."
            in description
        )

    async def test_the_description_says_how_to_retry_after_a_timeout(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = " ".join((tool.description or "").split())
        assert (
            "If a call times out, do not call this tool again first. Before you call again, make "
            + "sure that sharepoint_browse_folder does not show a folder named `name`."
        ) in description
        assert "safe to repeat" not in description

    def test_not_found_advice_says_nothing_was_created_and_names_a_tool_that_finds_it(
        self,
    ) -> None:
        assert "created nothing" in creator.GRAPH_NOT_FOUND
        assert "sharepoint_browse_folder" in creator.GRAPH_NOT_FOUND
        assert "sharepoint_search_files" in creator.GRAPH_NOT_FOUND

    def test_forbidden_advice_says_no_folder_was_created(self) -> None:
        assert _NOTHING_CREATED in creator.GRAPH_FORBIDDEN
