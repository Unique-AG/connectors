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
from fastmcp.tools import FunctionTool, Tool
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
from office_365_mcp.shared.files import FOLDER_HANDLE_SOURCES, ITEM_HANDLE_SOURCES, NAME_RULES
from office_365_mcp.shared.handles import (
    DriveFileHandle,
    DriveFolderHandle,
    drive_file_handle,
    drive_folder_handle,
)
from office_365_mcp.shared.notes import write_state_for
from office_365_mcp.shared.prose import PREVIEW_CHARACTERS
from office_365_mcp.shared.seam import WRITE_ADDITIVE, Confirm, GraphAdviceMiddleware
from office_365_mcp.tools import graph_advice, resolve
from office_365_mcp.tools import sharepoint_copy_item as copier
from office_365_mcp.tools.sharepoint_copy_item import CopyStarted, a_person_agrees, copy_item

_DRIVE_ID = "b!SYNTHETICDRIVE0000"
_OTHER_DRIVE_ID = "b!SYNTHETICDRIVE0001"
_FILE_ID = "01SYNTHETICFILE0000"
_FOLDER_ID = "01SYNTHETICFOLDER0000"
_DESTINATION_ID = "01SYNTHETICDESTINATION0000"
_ROOT_ID = "01SYNTHETICROOT0000"

_FILE_URI = DriveFileHandle(_DRIVE_ID, _FILE_ID).uri
_FOLDER_URI = DriveFolderHandle(_DRIVE_ID, _FOLDER_ID).uri
_DESTINATION_URI = DriveFolderHandle(_OTHER_DRIVE_ID, _DESTINATION_ID).uri

_FILE_PATH = "/drives/b%21SYNTHETICDRIVE0000/items/01SYNTHETICFILE0000"
_FOLDER_PATH = "/drives/b%21SYNTHETICDRIVE0000/items/01SYNTHETICFOLDER0000"
_DESTINATION_PATH = "/drives/b%21SYNTHETICDRIVE0001/items/01SYNTHETICDESTINATION0000"
_COPY_PATH = f"{_FILE_PATH}/copy"

_MONITOR = "https://contoso.sharepoint.invalid/_api/v2.0/monitor/SYNTHETICMONITOR0000"

_NOT_FOUND = {"error": {"code": "itemNotFound", "message": "not found"}}

_CONFLICT_BEHAVIOR = "@microsoft.graph.conflictBehavior"

_AGREE_EVERY_TIME = "This tool asks the user to agree before it creates anything, every time."
_SHOWN_TO_OTHERS = (
    "OneDrive and SharePoint can show the change to everyone who can open the folder."
)
_PERMISSIONS = (
    "The copy gets the permissions of the destination folder, not the permissions of the original."
)
_LATEST_VERSION_ONLY = (
    "It has only the latest version of a file, and Microsoft does not copy the metadata of the "
    + "original."
)
_NAME_CLASH = (
    "If the destination already holds an item with the same name, the copy fails. This failure "
    + "can come after this call returns, and then this tool cannot show it. To copy an item into "
    + "its own folder, give the copy a new `name`."
)
_RETRY = (
    "If a call times out, do not call this tool again first. Before you call again, make sure "
    + "that sharepoint_browse_folder does not show the copy in the destination."
)


def _file(
    *, item_id: str = _FILE_ID, name: str | None = "Plan.docx", drive_id: str = _DRIVE_ID
) -> dict[str, object]:
    return {
        "id": item_id,
        "name": name,
        "file": {"mimeType": "application/octet-stream"},
        "parentReference": {"driveId": drive_id, "id": "01SYNTHETICPARENT0000"},
    }


def _folder(
    *,
    item_id: str = _DESTINATION_ID,
    name: str | None = "Reports",
    drive_id: str = _OTHER_DRIVE_ID,
    root: bool = False,
    parent_path: str | None = None,
) -> dict[str, object]:
    return {
        "id": item_id,
        "name": name,
        "folder": {"childCount": 2},
        "parentReference": {
            "driveId": drive_id,
            **({} if parent_path is None else {"path": parent_path}),
        },
        **({"root": {}} if root else {}),
    }


def _reads(graph: respx.MockRouter, path: str, payload: Mapping[str, object]) -> respx.Route:
    return graph.get(path).mock(return_value=httpx.Response(200, json=dict(payload)))


def _both_read(graph: respx.MockRouter) -> None:
    _ = _reads(graph, _FILE_PATH, _file())
    _ = _reads(graph, _DESTINATION_PATH, _folder())


def _accepts(graph: respx.MockRouter, path: str = _COPY_PATH) -> respx.Route:
    return graph.post(path).mock(
        return_value=httpx.Response(202, content=b"", headers={"Location": _MONITOR})
    )


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
    item: str = _FILE_URI,
    to_folder: str = _DESTINATION_URI,
    name: str | None = None,
    confirm: Confirm = _agrees,
) -> CopyStarted:
    answer = await copy_item(client, item=item, to_folder=to_folder, name=name, confirm=confirm)
    assert isinstance(answer, CopyStarted), "this call was answered with a question, not a copy"
    return answer


async def _advised_copy(client: GraphServiceClient) -> str:
    async def copying(context: MiddlewareContext[CallToolRequestParams]) -> ToolResult:
        assert context.message.name == copier.TOOL_NAME
        _ = await _copy(client)
        raise AssertionError("Graph refused the copy, and the call still answered")

    middleware = GraphAdviceMiddleware(
        graph_advice(resolve(preset=None, enabled=(copier.TOOL_NAME,)))
    )
    context = MiddlewareContext(message=CallToolRequestParams(name=copier.TOOL_NAME, arguments={}))
    with pytest.raises(ToolError) as raised:
        _ = await middleware.on_call_tool(context, copying)
    return str(raised.value)


def _asking(asked: list[str]) -> Confirm:
    async def capturing(question: str, about: str) -> str | None:
        assert about
        asked.append(question)
        return None

    return capturing


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


def _made(router: respx.MockRouter) -> Sequence[Call]:
    return cast("Sequence[Call]", router.calls)


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    copier.register(mcp, transport)
    tool = await mcp.get_tool(copier.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


def _properties(parameters: Mapping[str, object]) -> Mapping[str, Mapping[str, object]]:
    return cast("Mapping[str, Mapping[str, object]]", parameters["properties"])


class TestWhatItSendsToGraph:
    async def test_an_agreed_copy_reads_the_item_and_the_folder_then_posts_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        copy = _accepts(graph)

        _ = await _copy(client)

        assert copy.call_count == 1
        assert [call.request.method for call in _made(graph)] == ["GET", "GET", "POST"]

    async def test_the_body_carries_the_destination_drive_and_folder_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        copy = _accepts(graph)

        _ = await _copy(client)

        assert _sent(copy) == {
            "parentReference": {"driveId": _OTHER_DRIVE_ID, "id": _DESTINATION_ID}
        }

    async def test_a_copy_inside_one_drive_names_that_drive_in_the_body(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _FILE_PATH, _file())
        _ = _reads(graph, _FOLDER_PATH, _folder(item_id=_FOLDER_ID, drive_id=_DRIVE_ID))
        copy = _accepts(graph)

        answer = await _copy(client, to_folder=_FOLDER_URI)

        assert _sent(copy) == {"parentReference": {"driveId": _DRIVE_ID, "id": _FOLDER_ID}}
        assert answer.destination_uri == _FOLDER_URI

    async def test_the_body_names_the_folder_by_the_id_that_the_read_gives(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _FILE_PATH, _file())
        _ = _reads(
            graph, "/drives/b%21SYNTHETICDRIVE0001/items/root", _folder(item_id=_ROOT_ID, root=True)
        )
        copy = _accepts(graph)

        answer = await _copy(client, to_folder=DriveFolderHandle(_OTHER_DRIVE_ID, "root").uri)

        assert _sent(copy)["parentReference"] == {"driveId": _OTHER_DRIVE_ID, "id": _ROOT_ID}
        assert answer.destination_uri == DriveFolderHandle(_OTHER_DRIVE_ID, _ROOT_ID).uri

    async def test_a_new_name_is_sent_in_the_body(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        copy = _accepts(graph)

        _ = await _copy(client, name="Plan (copy).docx")

        assert _sent(copy) == {
            "name": "Plan (copy).docx",
            "parentReference": {"driveId": _OTHER_DRIVE_ID, "id": _DESTINATION_ID},
        }

    async def test_a_folder_copy_body_carries_the_destination_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _FOLDER_PATH, _folder(item_id=_FOLDER_ID, name="Q1", drive_id=_DRIVE_ID))
        _ = _reads(graph, _DESTINATION_PATH, _folder())
        copy = _accepts(graph, f"{_FOLDER_PATH}/copy")

        _ = await _copy(client, item=_FOLDER_URI)

        assert _sent(copy) == {
            "parentReference": {"driveId": _OTHER_DRIVE_ID, "id": _DESTINATION_ID}
        }

    async def test_the_copy_asks_graph_to_fail_on_a_name_that_is_taken(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        copy = _accepts(graph)

        _ = await _copy(client)

        assert dict(copy.calls.last.request.url.params) == {_CONFLICT_BEHAVIOR: "fail"}

    async def test_the_copy_content_type_is_json(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        copy = _accepts(graph)

        _ = await _copy(client)

        assert copy.calls.last.request.headers["content-type"] == "application/json"

    async def test_the_monitor_address_is_never_read(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        _ = _accepts(graph)

        answer = await _copy(client)

        assert len(_made(graph)) == 3, "the two reads and the copy, and no call to the monitor"
        assert _MONITOR not in answer.model_dump_json()

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_copy_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        copy = graph.post(_COPY_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _copy(client)

        assert copy.call_count == 1, "no_retry means one attempt, however Graph answers"


class TestWhatItAnswers:
    async def test_an_empty_202_is_a_copy_that_started(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        _ = _accepts(graph)

        answer = await _copy(client)

        assert answer == CopyStarted(
            source_uri=_FILE_URI, destination_uri=_DESTINATION_URI, name="Plan.docx"
        )

    async def test_the_answer_names_the_new_name_when_one_is_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        _ = _accepts(graph)

        answer = await _copy(client, name="Plan (copy).docx")

        assert answer.name == "Plan (copy).docx"

    async def test_the_answer_name_is_null_when_graph_reports_no_name_for_the_original(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _FILE_PATH, _file(name=None))
        _ = _reads(graph, _DESTINATION_PATH, _folder())
        _ = _accepts(graph)

        answer = await _copy(client)

        assert answer.name is None

    async def test_a_folder_copy_answers_with_the_folder_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _FOLDER_PATH, _folder(item_id=_FOLDER_ID, name="Q1", drive_id=_DRIVE_ID))
        _ = _reads(graph, _DESTINATION_PATH, _folder())
        copy = _accepts(graph, f"{_FOLDER_PATH}/copy")

        answer = await _copy(client, item=_FOLDER_URI)

        assert copy.call_count == 1
        assert answer.source_uri == _FOLDER_URI
        assert answer.name == "Q1"


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            _FILE_ID,
            "Plan.docx",
            "https://contoso.sharepoint.invalid/sites/team/Shared%20Documents/Plan.docx",
            "",
            "   ",
            "sharepoint:///files/",
            "sharepoint:///files/b%21SYNTHETICDRIVE0000/",
            "sharepoint:///files/%20/%20",
            "onenote:///pages/1-SYNTHETICPAGE0000",
        ],
    )
    async def test_a_value_that_is_not_an_item_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError, match="takes a file handle or a folder handle"):
            _ = await _copy(client, item=value)

        assert len(_made(graph)) == 0, "a refused handle reads and writes nothing"

    async def test_the_item_refusal_names_the_tools_that_mint_a_handle(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await _copy(client, item="Plan.docx")

        assert ITEM_HANDLE_SOURCES in str(refused.value)
        assert "sharepoint_search_files" in str(refused.value)
        assert "sharepoint_browse_folder" in str(refused.value)

    async def test_the_folder_refusal_names_the_tools_that_mint_a_folder_handle(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await _copy(client, to_folder="Reports")

        assert FOLDER_HANDLE_SOURCES in str(refused.value)
        assert "`root_uri`" in str(refused.value)
        assert "sharepoint_list_drives" in str(refused.value)

    @pytest.mark.parametrize(
        "value",
        [
            _FILE_URI,
            _DESTINATION_ID,
            "Reports",
            "",
            "sharepoint:///folders/",
            "sharepoint:///folders/b%21SYNTHETICDRIVE0001/",
        ],
    )
    async def test_a_value_that_is_not_a_folder_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError, match="takes a folder handle in `to_folder`"):
            _ = await _copy(client, to_folder=value)

        assert len(_made(graph)) == 0, "a refused handle reads and writes nothing"

    async def test_the_item_handle_is_checked_before_the_folder_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="in `item`"):
            _ = await _copy(client, item="not a handle", to_folder="also not a handle")

        assert len(_made(graph)) == 0

    @pytest.mark.parametrize("name", ["Q1/Q2.docx", "~$Plan.docx", 'Plan "2".docx', "   "])
    async def test_a_name_that_microsoft_does_not_allow_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, name: str
    ) -> None:
        with pytest.raises(ToolError, match="Nothing was changed"):
            _ = await _copy(client, name=name)

        assert len(_made(graph)) == 0

    async def test_a_folder_copy_named_with_a_trailing_period_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _FOLDER_PATH, _folder(item_id=_FOLDER_ID, name="Q1", drive_id=_DRIVE_ID))
        _ = _reads(graph, _DESTINATION_PATH, _folder())
        copy = _accepts(graph, f"{_FOLDER_PATH}/copy")

        _ = await _copy(client, item=_FOLDER_URI, name="Q1.")

        assert _sent(copy)["name"] == "Q1."

    async def test_a_file_copy_takes_a_name_that_ends_with_a_period(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        copy = _accepts(graph)

        _ = await _copy(client, name="Q1.")

        assert _sent(copy)["name"] == "Q1."

    async def test_the_top_folder_of_a_drive_is_refused_before_anybody_is_asked(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _FOLDER_PATH, _folder(item_id=_FOLDER_ID, drive_id=_DRIVE_ID, root=True))
        _ = _reads(graph, _DESTINATION_PATH, _folder())
        copy = _accepts(graph, f"{_FOLDER_PATH}/copy")
        asked: list[str] = []

        with pytest.raises(ToolError, match="cannot copy the top folder of a drive"):
            _ = await _copy(client, item=_FOLDER_URI, confirm=_asking(asked))

        assert asked == []
        assert copy.call_count == 0

    async def test_a_destination_with_no_folder_facet_is_refused_before_anybody_is_asked(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _FILE_PATH, _file())
        _ = _reads(
            graph,
            _DESTINATION_PATH,
            _file(item_id=_DESTINATION_ID, name="Reports.docx", drive_id=_OTHER_DRIVE_ID),
        )
        copy = _accepts(graph)
        asked: list[str] = []

        with pytest.raises(ToolError, match="is not a folder"):
            _ = await _copy(client, confirm=_asking(asked))

        assert asked == []
        assert copy.call_count == 0


class TestGraphFailures:
    async def test_a_404_on_the_item_read_is_a_not_found_and_nothing_is_copied(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_FILE_PATH).mock(return_value=httpx.Response(404, json=_NOT_FOUND))
        _ = _reads(graph, _DESTINATION_PATH, _folder())
        copy = _accepts(graph)

        with pytest.raises(GraphNotFound):
            _ = await _copy(client)

        assert copy.call_count == 0

    async def test_a_404_on_the_folder_read_is_a_not_found_and_nothing_is_copied(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _FILE_PATH, _file())
        _ = graph.get(_DESTINATION_PATH).mock(return_value=httpx.Response(404, json=_NOT_FOUND))
        copy = _accepts(graph)

        with pytest.raises(GraphNotFound):
            _ = await _copy(client)

        assert copy.call_count == 0

    async def test_a_404_on_the_copy_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        _ = graph.post(_COPY_PATH).mock(return_value=httpx.Response(404, json=_NOT_FOUND))

        with pytest.raises(GraphNotFound):
            _ = await _copy(client)

    async def test_a_403_on_the_copy_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        _ = graph.post(_COPY_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _copy(client)

    async def test_a_403_on_the_copy_after_the_reads_reaches_the_model_as_item_access(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        copy = graph.post(_COPY_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        message = await _advised_copy(client)

        assert message.startswith(copier.GRAPH_FORBIDDEN)
        assert "HTTP 403" in message
        assert "administrator to grant" not in message
        assert "Files.ReadWrite.All" not in message
        assert copy.call_count == 1

    async def test_a_409_on_the_copy_is_a_conflict_and_is_sent_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        copy = graph.post(_COPY_PATH).mock(
            return_value=httpx.Response(
                409, json={"error": {"code": "nameAlreadyExists", "message": "Name already exists"}}
            )
        )

        with pytest.raises(GraphFailure) as failed:
            _ = await _copy(client)

        assert failed.value.status == 409
        assert copy.call_count == 1

    def test_not_found_advice_points_at_the_tools_that_find_items(self) -> None:
        assert "sharepoint_search_files" in copier.GRAPH_NOT_FOUND
        assert "sharepoint_browse_folder" in copier.GRAPH_NOT_FOUND
        assert "nothing was copied" in copier.GRAPH_NOT_FOUND

    def test_forbidden_advice_says_nothing_was_copied(self) -> None:
        assert "Nothing was copied." in copier.GRAPH_FORBIDDEN


class TestThePersonBetweenTheCopyAndTheDestination:
    async def test_every_copy_is_asked_about(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        copy = _accepts(graph)
        asked: list[str] = []

        _ = await _copy(client, confirm=_asking(asked))

        assert len(asked) == 1
        assert copy.call_count == 1

    async def test_a_refusal_copies_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        copy = _accepts(graph)

        with pytest.raises(ToolError, match="Nothing was copied"):
            _ = await _copy(client, confirm=_refuses)

        assert copy.call_count == 0

    async def test_the_question_names_the_item_and_the_destination_folder(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        _ = _accepts(graph)
        asked: list[str] = []

        _ = await _copy(client, confirm=_asking(asked))

        assert asked == ["Copy 'Plan.docx' into the folder 'Reports'?"]

    async def test_the_question_names_the_new_name_when_one_is_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        _ = _accepts(graph)
        asked: list[str] = []

        _ = await _copy(client, name="Plan (copy).docx", confirm=_asking(asked))

        assert asked == ["Copy 'Plan.docx' into the folder 'Reports' as 'Plan (copy).docx'?"]

    async def test_a_long_item_name_is_cut_in_the_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        long = "B" * 200 + ".xlsx"
        _ = _reads(graph, _FILE_PATH, _file(name=long))
        _ = _reads(graph, _DESTINATION_PATH, _folder())
        _ = _accepts(graph)
        asked: list[str] = []

        _ = await _copy(client, confirm=_asking(asked))

        assert asked == [f"Copy '{'B' * PREVIEW_CHARACTERS}…' into the folder 'Reports'?"]
        assert long not in asked[0]

    async def test_the_new_name_reaches_the_question_whole(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        new_name = "C" * 200 + ".docx"
        _both_read(graph)
        _ = _accepts(graph)
        asked: list[str] = []

        _ = await _copy(client, name=new_name, confirm=_asking(asked))

        assert asked == [f"Copy 'Plan.docx' into the folder 'Reports' as {new_name!r}?"]

    async def test_the_question_names_the_path_of_the_destination_folder(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _FILE_PATH, _file())
        _ = _reads(graph, _DESTINATION_PATH, _folder(parent_path="/drive/root:/Finance%20Team"))
        _ = _accepts(graph)
        asked: list[str] = []

        _ = await _copy(client, confirm=_asking(asked))

        assert asked == ["Copy 'Plan.docx' into the folder '/Finance Team/Reports'?"]

    async def test_the_question_names_the_top_of_a_drive_as_the_destination(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _FILE_PATH, _file())
        _ = _reads(graph, _DESTINATION_PATH, _folder(name="root", root=True))
        _ = _accepts(graph)
        asked: list[str] = []

        _ = await _copy(client, confirm=_asking(asked))

        assert asked == ["Copy 'Plan.docx' into the top folder of the drive?"]

    async def test_the_question_names_nothing_that_graph_did_not_report(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _FILE_PATH, _file(name=None))
        _ = _reads(graph, _DESTINATION_PATH, _folder(name=None))
        _ = _accepts(graph)
        asked: list[str] = []

        _ = await _copy(client, confirm=_asking(asked))

        assert asked == ["Copy an unnamed item into an unnamed folder?"]

    async def test_about_is_bound_to_both_handles_and_the_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        _ = _accepts(graph)
        bound: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert question
            bound.append(about)
            return None

        _ = await _copy(client, confirm=capturing)
        _ = await _copy(client, confirm=capturing)
        _ = await _copy(client, name="Plan (copy).docx", confirm=capturing)

        assert bound[0] == write_state_for(
            copier.TOOL_NAME, _DRIVE_ID, _FILE_ID, _OTHER_DRIVE_ID, _DESTINATION_ID, ""
        )
        assert bound[1] == bound[0]
        assert bound[2] != bound[0]

    @pytest.mark.parametrize(
        "answer",
        [
            DeclinedElicitation(),
            CancelledElicitation(),
            AcceptedElicitation(data="do not copy"),
            MCPError(METHOD_NOT_FOUND, "Method not found"),
            ToolError("the client refused the request"),
        ],
        ids=["declined", "cancelled", "another-answer", "cannot-ask", "client-error"],
    )
    async def test_no_refusal_is_ever_raised(self, answer: object) -> None:
        confirm = a_person_agrees(_context(answer))

        refusal = await confirm("Copy this item?", "synthetic-state")

        assert isinstance(refusal, str)
        assert refusal

    async def test_a_refusal_this_tool_words_opens_by_saying_nothing_was_copied(self) -> None:
        confirm = a_person_agrees(_context(DeclinedElicitation()))

        refusal = await confirm("Copy this item?", "synthetic-state")

        assert isinstance(refusal, str)
        assert refusal.startswith("Nothing was copied.")

    async def test_agreeing_answers_with_no_refusal(self) -> None:
        confirm = a_person_agrees(_context(AcceptedElicitation(data="copy")))

        assert await confirm("Copy this item?", "synthetic-state") is None


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


def _first_key(asked: InputRequiredResult) -> str:
    requests = asked.input_requests or {}
    return next(iter(requests))


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_reaches_the_copy(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        copy = _accepts(graph)

        answer = await copy_item(
            client,
            item=_FILE_URI,
            to_folder=_DESTINATION_URI,
            confirm=a_person_agrees(_modern_context()),
        )

        assert isinstance(answer, InputRequiredResult)
        assert answer.request_state == write_state_for(
            copier.TOOL_NAME, _DRIVE_ID, _FILE_ID, _OTHER_DRIVE_ID, _DESTINATION_ID, ""
        )
        assert copy.call_count == 0

    async def test_the_first_round_asks_the_question_this_tool_words(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        _ = _accepts(graph)

        answer = await copy_item(
            client,
            item=_FILE_URI,
            to_folder=_DESTINATION_URI,
            confirm=a_person_agrees(_modern_context()),
        )

        assert isinstance(answer, InputRequiredResult)
        request = (answer.input_requests or {})[_first_key(answer)]
        assert isinstance(request, ElicitRequest)
        params = request.params
        assert isinstance(params, ElicitRequestFormParams)
        assert params.message == "Copy 'Plan.docx' into the folder 'Reports'?"

    async def test_the_second_round_copies_under_the_state_it_was_agreed_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        copy = _accepts(graph)

        first = await copy_item(
            client,
            item=_FILE_URI,
            to_folder=_DESTINATION_URI,
            confirm=a_person_agrees(_modern_context()),
        )
        assert isinstance(first, InputRequiredResult)

        answer = await copy_item(
            client,
            item=_FILE_URI,
            to_folder=_DESTINATION_URI,
            confirm=a_person_agrees(
                _modern_context(
                    answers={
                        _first_key(first): ElicitResult(action="accept", content={"value": "copy"})
                    },
                    state=first.request_state,
                )
            ),
        )

        assert isinstance(answer, CopyStarted)
        assert copy.call_count == 1

    async def test_an_answer_bound_to_another_request_copies_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        copy = _accepts(graph)

        first = await copy_item(
            client,
            item=_FILE_URI,
            to_folder=_DESTINATION_URI,
            confirm=a_person_agrees(_modern_context()),
        )
        assert isinstance(first, InputRequiredResult)

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await copy_item(
                client,
                item=_FILE_URI,
                to_folder=_DESTINATION_URI,
                name="Plan (copy).docx",
                confirm=a_person_agrees(
                    _modern_context(
                        answers={
                            _first_key(first): ElicitResult(
                                action="accept", content={"value": "copy"}
                            )
                        },
                        state=first.request_state,
                    )
                ),
            )

        assert copy.call_count == 0


class TestTheClientThatCannotAsk:
    async def test_a_client_that_cannot_ask_copies_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _both_read(graph)
        copy = _accepts(graph)
        confirm = a_person_agrees(_context(MCPError(METHOD_NOT_FOUND, "Method not found")))

        with pytest.raises(ToolError, match="does not support elicitation"):
            _ = await _copy(client, confirm=confirm)

        assert copy.call_count == 0


class TestHowItDeclaresItself:
    def test_the_permission_is_files_read_write_all(self) -> None:
        assert copier.GRAPH_PERMISSIONS == ("Files.ReadWrite.All",)

    def test_its_change_is_shown_by_the_folder_browser(self) -> None:
        assert copier.CHANGE_SHOWN_BY == ("sharepoint_browse_folder",)

    def test_the_call_example_is_a_file_handle_and_a_folder_handle(self) -> None:
        example = copier.GRAPH_CALL_EXAMPLE

        assert set(example) == {"item", "to_folder"}
        assert drive_file_handle(cast("str", example["item"])) is not None
        assert drive_folder_handle(cast("str", example["to_folder"])) is not None

    async def test_the_call_example_reaches_graph_with_an_agreeing_client(
        self, transport: httpx.AsyncClient, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _FILE_PATH, _file())
        _ = _reads(graph, _FOLDER_PATH, _folder(item_id=_FOLDER_ID, drive_id=_DRIVE_ID))
        copy = _accepts(graph)
        _parameters, tool = await _registered(transport)
        assert isinstance(tool, FunctionTool)

        answer = cast(
            "CopyStarted | InputRequiredResult",
            await tool.fn(
                **copier.GRAPH_CALL_EXAMPLE,
                ctx=_context(AcceptedElicitation(data="copy")),
                client=client,
            ),
        )

        assert isinstance(answer, CopyStarted)
        assert copy.call_count == 1

    async def test_it_takes_an_item_a_folder_and_a_name_and_no_others(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert set(_properties(parameters)) == {"item", "to_folder", "name"}
        assert set(cast("list[str]", parameters["required"])) == {"item", "to_folder"}

    @pytest.mark.parametrize("word", ["client", "ctx", "context", "token", "graph"])
    async def test_no_wiring_of_this_server_is_published_as_an_argument(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert not [name for name in _properties(parameters) if word in name.casefold()]

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

    async def test_its_title_is_copy_an_item(self, transport: httpx.AsyncClient) -> None:
        _parameters, tool = await _registered(transport)

        assert tool.title == "Copy an Item"

    @pytest.mark.parametrize(
        "sentence",
        [
            _AGREE_EVERY_TIME,
            _SHOWN_TO_OTHERS,
            _PERMISSIONS,
            _LATEST_VERSION_ONLY,
            _NAME_CLASH,
            _RETRY,
        ],
    )
    async def test_the_description_keeps_its_guarantees(
        self, transport: httpx.AsyncClient, sentence: str
    ) -> None:
        _parameters, tool = await _registered(transport)

        assert sentence in (tool.description or "")

    async def test_the_lead_paragraph_ends_by_saying_who_can_see_the_change(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        lead, _notes = (tool.description or "").split("\n\nNotes:\n")
        assert lead.endswith(_SHOWN_TO_OTHERS)

    async def test_the_lead_leaves_the_handle_sources_to_the_arguments(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        lead = (tool.description or "").split("\n\nNotes:")[0]
        assert "sharepoint_search_files" not in lead
        assert "sharepoint_browse_folder" not in lead
        assert "sharepoint_resolve_url" not in lead

    async def test_the_description_does_not_offer_a_way_to_follow_the_copy(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = (tool.description or "").casefold()
        assert "monitor" not in description
        assert "onenote_get_operation" not in description

    async def test_the_description_is_45_to_210_words(self, transport: httpx.AsyncClient) -> None:
        _parameters, tool = await _registered(transport)

        assert 45 <= len((tool.description or "").split()) <= 210

    async def test_every_argument_is_described_in_15_to_60_words(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        counts = {
            name: len(str(schema.get("description", "")).split())
            for name, schema in _properties(parameters).items()
        }
        assert all(15 <= count <= 60 for count in counts.values()), counts

    async def test_the_item_description_names_every_handle_source(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert ITEM_HANDLE_SOURCES in str(_properties(parameters)["item"]["description"])

    async def test_the_folder_description_names_every_folder_handle_source(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        described = str(_properties(parameters)["to_folder"]["description"])
        assert FOLDER_HANDLE_SOURCES in described
        assert "`root_uri`" in described
        assert "sharepoint_list_drives" in described

    async def test_the_name_description_states_the_name_rules(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        described = str(_properties(parameters)["name"]["description"])
        assert NAME_RULES in described
        assert "do not accept" not in described

    def test_every_answer_field_is_described_in_15_to_60_words(self) -> None:
        counts = {
            name: len((field.description or "").split())
            for name, field in CopyStarted.model_fields.items()
        }

        assert set(counts) == {"source_uri", "destination_uri", "name"}
        assert all(15 <= count <= 60 for count in counts.values()), counts
