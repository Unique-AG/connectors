import hashlib
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError, ValidationError
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
from office_365_mcp.shared.files import NAME_RULES, DriveItemSummary
from office_365_mcp.shared.handles import DriveFileHandle, DriveFolderHandle
from office_365_mcp.shared.notes import write_state_for
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Advised,
    Confirm,
    GraphAdviceMiddleware,
    ToolAdvice,
)
from office_365_mcp.tools import sharepoint_create_text_file as creator
from office_365_mcp.tools.sharepoint_create_text_file import a_person_agrees, create_text_file

_DRIVE_ID = "b-SYNTHETIC-drive-0001"
_FOLDER_ID = "01SYNTHETICREPORTS"
_ROOT_ID = "01SYNTHETICROOT"
_FILE_ID = "01SYNTHETICNEWFILE"

_FOLDER_URI = DriveFolderHandle(_DRIVE_ID, _FOLDER_ID).uri

_FOLDER_ROUTE = f"/drives/{_DRIVE_ID}/items/{_FOLDER_ID}"
_FILE_ROUTE = f"/drives/{_DRIVE_ID}/items/{_FILE_ID}"

_NAME = "notes.txt"
_CONTENT = "Ship it now."

_CONFLICT_FAILS = "@microsoft.graph.conflictBehavior=fail"

_ASKS_EVERY_TIME = "This tool asks the user to agree before it creates anything, every time."
_SHOWN_TO_OTHERS = (
    "OneDrive and SharePoint can show the change to everyone who can open the folder."
)
_NEVER_REPLACES = "If a file named `name` is already there, Microsoft refuses and creates nothing."
_CHECK_BEFORE_A_RETRY = (
    "If a call times out, do not call this tool again first. Before you call again, make sure "
    + "that sharepoint_browse_folder does not show a file named `name`."
)


def _folder_payload(
    *,
    item_id: str = _FOLDER_ID,
    name: str | None = "Reports",
    is_folder: bool = True,
    is_root: bool = False,
    drive_type: str = "business",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": item_id,
        "name": name,
        "webUrl": f"https://contoso.sharepoint.invalid/items/{item_id}",
        "parentReference": {"driveId": _DRIVE_ID, "driveType": drive_type, "id": _ROOT_ID},
    }
    if is_folder:
        payload["folder"] = {"childCount": 2}
    else:
        payload["file"] = {"mimeType": "application/pdf"}
    if is_root:
        payload["root"] = {}
    return payload


def _created_payload(
    *, name: str = _NAME, with_drive: bool = True, file_id: str | None = _FILE_ID
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "size": 12,
        "webUrl": f"https://contoso.sharepoint.invalid/items/{_FILE_ID}",
        "createdDateTime": "2026-09-30T08:00:00Z",
        "file": {"mimeType": "text/plain"},
    }
    if file_id is not None:
        payload["id"] = file_id
    if with_drive:
        payload["parentReference"] = {
            "driveId": _DRIVE_ID,
            "driveType": "business",
            "id": _FOLDER_ID,
        }
    return payload


def _reads_folder(
    graph: respx.MockRouter, payload: Mapping[str, object] | None = None
) -> respx.Route:
    body = dict(_folder_payload() if payload is None else payload)
    return graph.get(_FOLDER_ROUTE).mock(return_value=httpx.Response(200, json=body))


def _writes(graph: respx.MockRouter, payload: Mapping[str, object] | None = None) -> respx.Route:
    body = dict(_created_payload() if payload is None else payload)
    return graph.route(method="PUT").mock(return_value=httpx.Response(201, json=body))


def _no_write(graph: respx.MockRouter) -> respx.Route:
    return graph.route(method="PUT").mock(return_value=httpx.Response(201))


def _name_conflict(graph: respx.MockRouter) -> respx.Route:
    return graph.route(method="PUT").mock(
        return_value=httpx.Response(
            409, json={"error": {"code": "nameAlreadyExists", "message": "exists"}}
        )
    )


async def _agrees(question: str, about: str) -> str | None:
    assert question, "the person was asked nothing at all"
    assert about, "the answer was bound to nothing"
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return "No file was created."


async def _create(
    client: GraphServiceClient,
    *,
    folder: str = _FOLDER_URI,
    name: str = _NAME,
    content: str = _CONTENT,
    confirm: Confirm = _agrees,
) -> DriveItemSummary:
    created = await create_text_file(
        client, folder=folder, name=name, content=content, confirm=confirm
    )
    assert isinstance(created, DriveItemSummary), "this call was answered with a question"
    return created


def _calls(graph: respx.MockRouter) -> Sequence[Call]:
    return cast("Sequence[Call]", graph.calls)


def _sent_path(route: respx.Route) -> str:
    return route.calls.last.request.url.raw_path.decode("ascii")


def _asking(asked: list[str]) -> Confirm:
    async def counting(question: str, about: str) -> str | None:
        assert about
        asked.append(question)
        return None

    return counting


def _binding(bound: list[str]) -> Confirm:
    async def capturing(question: str, about: str) -> str | None:
        assert question
        bound.append(about)
        return None

    return capturing


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    creator.register(mcp, transport)
    tool = await mcp.get_tool(creator.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


def _properties(parameters: Mapping[str, object]) -> Mapping[str, Mapping[str, object]]:
    return cast("Mapping[str, Mapping[str, object]]", parameters["properties"])


class TestWhatItSendsToGraph:
    async def test_it_puts_the_text_under_the_folder_by_name_and_never_replaces(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        route = _writes(graph)

        _ = await _create(client)

        assert route.call_count == 1
        assert route.calls.last.request.method == "PUT"
        assert _sent_path(route) == (
            f"/v1.0/drives/{_DRIVE_ID}/items/{_FOLDER_ID}:/{_NAME}:/content?{_CONFLICT_FAILS}"
        )

    async def test_a_name_with_spaces_and_non_ascii_letters_is_percent_encoded_on_the_wire(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        route = _writes(graph, _created_payload(name="Notes für Zoë 2026.md"))

        _ = await _create(client, name="Notes für Zoë 2026.md")

        assert _sent_path(route) == (
            f"/v1.0/drives/{_DRIVE_ID}/items/{_FOLDER_ID}"
            + ":/Notes%20f%C3%BCr%20Zo%C3%AB%202026.md:/content"
            + f"?{_CONFLICT_FAILS}"
        )

    async def test_a_name_with_url_punctuation_stays_one_encoded_path_segment(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        route = _writes(graph)

        _ = await _create(client, name="a+b&c=d;e@f's (1).txt")

        assert _sent_path(route) == (
            f"/v1.0/drives/{_DRIVE_ID}/items/{_FOLDER_ID}"
            + ":/a%2Bb%26c%3Dd%3Be%40f%27s%20%281%29.txt:/content"
            + f"?{_CONFLICT_FAILS}"
        )

    @pytest.mark.parametrize(
        ("name", "encoded"), [("a#b.txt", "a%23b.txt"), ("50%.txt", "50%25.txt")]
    )
    async def test_a_hash_or_a_percent_sign_in_the_name_is_percent_encoded_on_the_wire(
        self, client: GraphServiceClient, graph: respx.MockRouter, name: str, encoded: str
    ) -> None:
        _ = _reads_folder(graph)
        route = _writes(graph, _created_payload(name=name))

        _ = await _create(client, name=name)

        assert _sent_path(route) == (
            f"/v1.0/drives/{_DRIVE_ID}/items/{_FOLDER_ID}:/{encoded}:/content?{_CONFLICT_FAILS}"
        )

    async def test_the_ids_of_the_handle_are_percent_encoded_on_the_wire(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.route(method="GET").mock(
            return_value=httpx.Response(200, json=_folder_payload(item_id="01!folder"))
        )
        route = _writes(graph)

        _ = await _create(client, folder=DriveFolderHandle("b!drive 1", "01!folder").uri)

        assert _sent_path(route).startswith("/v1.0/drives/b%21drive%201/items/01%21folder:/")

    async def test_the_write_goes_under_the_id_graph_returned_for_the_folder(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = graph.get(f"/drives/{_DRIVE_ID}/items/root").mock(
            return_value=httpx.Response(
                200, json=_folder_payload(item_id=_ROOT_ID, name="root", is_root=True)
            )
        )
        route = _writes(graph)

        _ = await _create(client, folder=DriveFolderHandle(_DRIVE_ID, "root").uri)

        assert read.call_count == 1
        assert _sent_path(route).startswith(f"/v1.0/drives/{_DRIVE_ID}/items/{_ROOT_ID}:/")

    async def test_the_content_type_is_plain_text_in_utf_8(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        route = _writes(graph)

        _ = await _create(client)

        assert route.calls.last.request.headers["Content-Type"] == "text/plain; charset=utf-8"

    async def test_the_body_is_the_text_as_utf_8_bytes_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        route = _writes(graph)
        text = 'Zoë: 100 % done\n"quoted" <b>not html</b>\n'

        _ = await _create(client, content=text)

        assert route.calls.last.request.content == text.encode("utf-8")

    async def test_a_text_at_the_cap_reaches_graph_whole(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        route = _writes(graph)
        text = "line\n" * (creator.MAX_CONTENT_CHARACTERS // 5)

        _ = await _create(client, content=text)

        assert len(text) == creator.MAX_CONTENT_CHARACTERS
        assert route.calls.last.request.content == text.encode("utf-8")

    async def test_it_reads_the_folder_once_and_then_writes_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads_folder(graph)
        route = _writes(graph)

        _ = await _create(client)

        assert read.call_count == 1
        assert route.call_count == 1
        assert [call.request.method for call in _calls(graph)] == ["GET", "PUT"]

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_write_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        route = graph.route(method="PUT").mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _create(client)

        assert route.call_count == 1


class TestWhatItRefusesBeforeGraph:
    @pytest.mark.parametrize(
        "folder",
        [
            "Reports",
            _FOLDER_ID,
            "https://contoso.sharepoint.invalid/sites/team/Shared%20Documents/Reports",
            DriveFileHandle(_DRIVE_ID, _FILE_ID).uri,
            "sharepoint:///folders/",
            "sharepoint:///folders/%20/%20",
        ],
    )
    async def test_a_value_that_is_not_a_folder_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, folder: str
    ) -> None:
        with pytest.raises(ToolError, match="takes a folder handle"):
            _ = await _create(client, folder=folder)

        assert _calls(graph) == []

    async def test_the_handle_refusal_says_where_a_folder_handle_comes_from(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await _create(client, folder="Reports")

        assert str(refused.value).startswith("No file was created.")
        assert "sharepoint_browse_folder" in str(refused.value)
        assert "`parent_uri`" in str(refused.value)
        assert "`root_uri`" in str(refused.value)

    @pytest.mark.parametrize("name", ["a/b.txt", "a:b.txt", 'a"b.txt', "~$notes.txt", "   "])
    async def test_a_name_microsoft_does_not_allow_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, name: str
    ) -> None:
        with pytest.raises(ToolError, match="does not allow this name"):
            _ = await _create(client, name=name)

        assert _calls(graph) == []

    @pytest.mark.parametrize(
        "name",
        ["report.docx", "budget.xlsx", "deck.pptx", "scan.pdf", "photo.png", "notes", "notes."],
    )
    async def test_a_name_that_is_not_a_text_file_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, name: str
    ) -> None:
        with pytest.raises(ToolError, match="writes text only") as refused:
            _ = await _create(client, name=name)

        assert _calls(graph) == []
        assert str(refused.value).startswith("No file was created.")
        assert "cannot create a Word, Excel, PowerPoint or PDF file" in str(refused.value)

    @pytest.mark.parametrize(
        "name",
        [f"notes.{extension}" for extension in creator.TEXT_EXTENSIONS] + ["README.MD"],
    )
    async def test_every_text_extension_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, name: str
    ) -> None:
        _ = _reads_folder(graph)
        route = _writes(graph, _created_payload(name=name))

        _ = await _create(client, name=name)

        assert route.call_count == 1

    def test_the_text_extensions_are_the_closed_set_this_tool_signed_off_on(self) -> None:
        assert set(creator.TEXT_EXTENSIONS) == {
            "txt",
            "md",
            "csv",
            "tsv",
            "json",
            "xml",
            "html",
            "htm",
            "yaml",
            "yml",
            "log",
        }

    async def test_too_much_text_is_refused_by_the_schema_and_never_reaches_graph(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _parameters, tool = await _registered(transport)

        with pytest.raises(ValidationError, match="at most"):
            _ = await tool.run(
                {
                    "folder": _FOLDER_URI,
                    "name": _NAME,
                    "content": "x" * (creator.MAX_CONTENT_CHARACTERS + 1),
                }
            )

        assert _calls(graph) == []

    async def test_an_item_that_is_not_a_folder_is_refused_without_a_question_or_a_write(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads_folder(graph, _folder_payload(is_folder=False))
        route = _no_write(graph)
        asked: list[str] = []

        with pytest.raises(ToolError, match="not a folder"):
            _ = await _create(client, confirm=_asking(asked))

        assert read.call_count == 1
        assert asked == []
        assert route.call_count == 0


class TestThePersonBetweenTheRequestAndTheFile:
    async def test_it_asks_every_time_even_in_the_users_own_onedrive(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph, _folder_payload(drive_type="personal"))
        route = _writes(graph)
        asked: list[str] = []

        _ = await _create(client, confirm=_asking(asked))
        _ = await _create(client, confirm=_asking(asked))

        assert len(asked) == 2
        assert route.call_count == 2

    async def test_the_question_names_the_file_its_length_the_folder_and_the_opening(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        _ = _writes(graph)
        asked: list[str] = []

        _ = await _create(client, confirm=_asking(asked))

        assert asked == [
            "Create the text file 'notes.txt' (12 characters) in the folder 'Reports'? "
            + "It starts: 'Ship it now.'"
        ]

    async def test_the_top_folder_of_a_drive_is_named_as_such(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph, _folder_payload(name="root", is_root=True))
        _ = _writes(graph)
        asked: list[str] = []

        _ = await _create(client, confirm=_asking(asked))

        assert "in the top folder of its drive?" in asked[0]
        assert "'root'" not in asked[0]

    async def test_a_folder_graph_named_nothing_falls_back_to_an_unnamed_folder(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph, _folder_payload(name=None))
        _ = _writes(graph)
        asked: list[str] = []

        _ = await _create(client, confirm=_asking(asked))

        assert "in an unnamed folder?" in asked[0]

    async def test_a_long_text_is_counted_whole_and_cut_in_the_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        _ = _writes(graph)
        asked: list[str] = []

        _ = await _create(client, content="x" * 500, confirm=_asking(asked))

        assert "(500 characters)" in asked[0]
        assert asked[0].endswith(f"It starts: '{'x' * 120}…'")

    async def test_a_refusal_writes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        route = _no_write(graph)

        with pytest.raises(ToolError, match="No file was created"):
            _ = await _create(client, confirm=_refuses)

        assert route.call_count == 0, "a declined create still reached the folder"

    async def test_a_client_that_cannot_ask_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        route = _no_write(graph)
        confirm = a_person_agrees(_context(MCPError(METHOD_NOT_FOUND, "Method not found")))

        with pytest.raises(ToolError, match="does not support elicitation"):
            _ = await _create(client, confirm=confirm)

        assert route.call_count == 0

    async def test_about_is_bound_to_the_tool_the_folder_the_name_and_the_text(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        _ = _writes(graph)
        bound: list[str] = []

        _ = await _create(client, confirm=_binding(bound))

        assert bound == [
            write_state_for(
                creator.TOOL_NAME,
                _DRIVE_ID,
                _FOLDER_ID,
                _NAME,
                hashlib.sha256(_CONTENT.encode("utf-8")).hexdigest(),
            )
        ]

    async def test_two_identical_calls_bind_the_same_about_and_a_changed_text_a_different_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        _ = _writes(graph)
        bound: list[str] = []

        _ = await _create(client, content="one", confirm=_binding(bound))
        _ = await _create(client, content="one", confirm=_binding(bound))
        _ = await _create(client, content="two", confirm=_binding(bound))

        assert bound[0] == bound[1]
        assert bound[0] != bound[2]

    async def test_a_changed_name_binds_a_different_about(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        _ = _writes(graph)
        bound: list[str] = []

        _ = await _create(client, name="one.txt", confirm=_binding(bound))
        _ = await _create(client, name="two.txt", confirm=_binding(bound))

        assert bound[0] != bound[1]


class TestWhatItAnswers:
    async def test_the_answer_is_the_new_file_with_a_file_handle_and_its_folder(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        _ = _writes(graph)

        answer = await _create(client)

        assert answer.uri == DriveFileHandle(_DRIVE_ID, _FILE_ID).uri
        assert answer.parent_uri == _FOLDER_URI
        assert answer.is_folder is False
        assert answer.name == _NAME
        assert answer.mime_type == "text/plain"

    async def test_an_answer_with_no_drive_is_read_again_by_the_new_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        _ = _writes(graph, _created_payload(with_drive=False))
        reread = graph.get(_FILE_ROUTE).mock(
            return_value=httpx.Response(200, json=_created_payload())
        )

        answer = await _create(client)

        assert reread.call_count == 1
        assert answer.uri == DriveFileHandle(_DRIVE_ID, _FILE_ID).uri

    async def test_a_complete_answer_is_not_read_again(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        _ = _writes(graph)
        reread = graph.get(_FILE_ROUTE).mock(
            return_value=httpx.Response(200, json=_created_payload())
        )

        _ = await _create(client)

        assert reread.call_count == 0

    async def test_a_failed_second_read_says_that_the_file_was_created(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        route = _writes(graph, _created_payload(with_drive=False))
        _ = graph.get(_FILE_ROUTE).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(Advised, match="created the file") as raised:
            _ = await _create(client)

        assert isinstance(raised.value.__cause__, GraphFailure)
        assert "Do not call this tool again for this file." in str(raised.value)
        assert route.call_count == 1

    async def test_an_answer_with_no_id_says_that_the_file_was_created(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        _ = _writes(graph, _created_payload(with_drive=False, file_id=None))

        with pytest.raises(Advised, match="created the file"):
            _ = await _create(client)


class TestTheFailuresItPassesOn:
    async def test_a_file_of_the_same_name_is_a_conflict_and_is_sent_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        route = _name_conflict(graph)

        with pytest.raises(GraphFailure) as raised:
            _ = await _create(client)

        assert raised.value.status == 409
        assert not isinstance(raised.value, Advised)
        assert route.call_count == 1

    async def test_a_file_of_the_same_name_reaches_the_model_as_the_shared_name_advice(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        _ = _name_conflict(graph)

        async def creating(context: MiddlewareContext[CallToolRequestParams]) -> ToolResult:
            _ = context
            _ = await _create(client)
            raise AssertionError("a name conflict created the file anyway")

        advice = GraphAdviceMiddleware(
            {
                creator.TOOL_NAME: ToolAdvice(
                    permissions=creator.GRAPH_PERMISSIONS,
                    not_found=creator.GRAPH_NOT_FOUND,
                    shown_by=creator.CHANGE_SHOWN_BY,
                )
            }
        )
        context = MiddlewareContext(
            message=CallToolRequestParams(name=creator.TOOL_NAME, arguments={})
        )
        with pytest.raises(ToolError) as raised:
            _ = await advice.on_call_tool(context, creating)

        assert "already has the same name" in str(raised.value)
        assert "HTTP 409" in str(raised.value)

    async def test_a_refused_write_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        _ = graph.route(method="PUT").mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _create(client)

    async def test_a_missing_folder_is_a_not_found_and_nothing_is_asked_or_written(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_FOLDER_ROUTE).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )
        route = _no_write(graph)
        asked: list[str] = []

        with pytest.raises(GraphNotFound):
            _ = await _create(client, confirm=_asking(asked))

        assert asked == []
        assert route.call_count == 0

    async def test_the_call_example_reaches_graph_with_an_agreeing_client(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        example = cast("Mapping[str, str]", creator.GRAPH_CALL_EXAMPLE)
        read = graph.route(method="GET").mock(
            return_value=httpx.Response(200, json=_folder_payload())
        )
        route = _writes(graph)

        _ = await _create(
            client, folder=example["folder"], name=example["name"], content=example["content"]
        )

        assert read.call_count == 1
        assert route.call_count == 1

    def test_the_not_found_advice_says_nothing_was_created_and_names_tools_that_find_it(
        self,
    ) -> None:
        assert "created nothing" in creator.GRAPH_NOT_FOUND
        assert "sharepoint_browse_folder" in creator.GRAPH_NOT_FOUND
        assert "sharepoint_search_files" in creator.GRAPH_NOT_FOUND


class TestHowItDeclaresItself:
    def test_the_permission_is_files_read_write_all(self) -> None:
        assert creator.GRAPH_PERMISSIONS == ("Files.ReadWrite.All",)

    def test_its_write_step_is_create_text_file(self) -> None:
        assert creator.STEP_CREATE_FILE == "create_text_file"

    def test_sharepoint_browse_folder_shows_the_change(self) -> None:
        assert creator.CHANGE_SHOWN_BY == ("sharepoint_browse_folder",)

    def test_the_call_example_is_arguments_the_tool_accepts(self) -> None:
        assert set(creator.GRAPH_CALL_EXAMPLE) == {"folder", "name", "content"}

    async def test_it_announces_itself_as_a_write_that_destroys_nothing(
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
        assert annotations.open_world_hint is WRITE_ADDITIVE["openWorldHint"]
        assert tool.title == "Create a Text File"

    async def test_it_takes_folder_name_and_content_and_no_others(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert set(_properties(parameters)) == {"folder", "name", "content"}
        assert cast("list[str]", parameters["required"]) == ["folder", "name", "content"]

    async def test_no_argument_accepts_bytes_or_base64(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)

        for spec in _properties(parameters).values():
            assert spec["type"] == "string"
            assert "contentEncoding" not in spec
            assert "contentMediaType" not in spec
            assert "format" not in spec
        assert "as plain text" in cast("str", _properties(parameters)["content"]["description"])

    async def test_the_content_schema_caps_the_text(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)

        content = _properties(parameters)["content"]
        assert content["maxLength"] == creator.MAX_CONTENT_CHARACTERS
        assert content["minLength"] == 1
        assert "1,000,000 characters" in cast("str", content["description"])

    async def test_the_folder_description_names_every_tool_that_mints_a_folder_handle(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        described = cast("str", _properties(parameters)["folder"]["description"])
        for tool in (
            "sharepoint_browse_folder",
            "sharepoint_search_files",
            "sharepoint_list_drives",
        ):
            assert tool in described
        assert "`parent_uri`" in described
        assert "`root_uri` of a drive" in described

    async def test_the_name_description_lists_every_text_extension(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        description = cast("str", _properties(parameters)["name"]["description"])
        assert all(f"`.{extension}`" in description for extension in creator.TEXT_EXTENSIONS)
        assert NAME_RULES in description

    async def test_the_description_carries_the_canonical_sentences(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert _ASKS_EVERY_TIME in description
        assert _NEVER_REPLACES in description
        assert _CHECK_BEFORE_A_RETRY in description
        assert "without a question" not in description
        assert "safe to repeat" not in description

    async def test_the_lead_paragraph_ends_by_saying_who_can_see_the_change(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        lead, _notes = (tool.description or "").split("\n\nNotes:\n")
        assert lead.endswith(_SHOWN_TO_OTHERS)

    async def test_the_description_has_the_house_shape(self, transport: httpx.AsyncClient) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        _lead, notes = description.split("\n\nNotes:\n")
        bullets = [line for line in notes.splitlines() if line.startswith("- ")]
        assert 1 <= len(bullets) <= 3
        assert 45 <= len(description.split()) <= 210

    async def test_the_description_promises_no_overwrite_and_no_binary_upload(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = (tool.description or "").casefold()
        assert "it cannot replace a file or upload a binary file" in description
        assert "overwrite" not in description
        assert "base64" not in description
        assert "exists the moment this tool returns" not in description
        assert "no review step" not in description


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


async def _round(
    client: GraphServiceClient, *, confirm: Confirm
) -> DriveItemSummary | InputRequiredResult:
    return await create_text_file(
        client, folder=_FOLDER_URI, name=_NAME, content=_CONTENT, confirm=confirm
    )


def _the_question(answer: DriveItemSummary | InputRequiredResult) -> tuple[str, str, list[str]]:
    assert isinstance(answer, InputRequiredResult), "the question was never put to anybody"
    requests = answer.input_requests or {}
    assert len(requests) == 1, f"one question per call, and this one asked {sorted(requests)}"
    key = next(iter(requests))
    request = requests[key]
    assert isinstance(request, ElicitRequest)
    params = request.params
    assert isinstance(params, ElicitRequestFormParams), "the question is not one a client can fill"
    assert params.message, "the person is asked nothing at all"
    schema = cast("Mapping[str, object]", params.requested_schema)
    properties = cast("Mapping[str, object]", schema["properties"])
    value = cast("Mapping[str, object]", properties["value"])
    choices = cast("list[str]", value["enum"])
    assert answer.request_state is not None, "the answer was bound to nothing"
    return key, answer.request_state, choices


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_reaches_the_write(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads_folder(graph)
        route = _no_write(graph)

        answer = await _round(client, confirm=a_person_agrees(_modern_context()))

        _key, _state, _choices = _the_question(answer)
        assert read.call_count == 1
        assert route.call_count == 0, "an unanswered question created the file anyway"

    async def test_the_choices_are_create_and_do_not_create(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        _ = _no_write(graph)

        answer = await _round(client, confirm=a_person_agrees(_modern_context()))

        _key, _state, choices = _the_question(answer)
        assert choices == ["create", "do not create"]

    async def test_the_second_round_creates_the_file_it_was_agreed_to_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        route = _writes(graph)
        key, state, _choices = _the_question(
            await _round(client, confirm=a_person_agrees(_modern_context()))
        )

        answer = await _round(
            client,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": "create"})},
                    state=state,
                )
            ),
        )

        assert isinstance(answer, DriveItemSummary)
        assert route.call_count == 1, "the agreed create did not happen exactly once"

    async def test_a_second_round_the_person_declined_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        route = _no_write(graph)
        key, state, _choices = _the_question(
            await _round(client, confirm=a_person_agrees(_modern_context()))
        )

        with pytest.raises(ToolError, match="did not agree") as raised:
            _ = await _round(
                client,
                confirm=a_person_agrees(
                    _modern_context(answers={key: ElicitResult(action="decline")}, state=state)
                ),
            )

        assert str(raised.value).startswith("No file was created.")
        assert route.call_count == 0

    async def test_an_answer_bound_to_another_request_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        route = _no_write(graph)
        key, _state, _choices = _the_question(
            await _round(client, confirm=a_person_agrees(_modern_context()))
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await _round(
                client,
                confirm=a_person_agrees(
                    _modern_context(
                        answers={key: ElicitResult(action="accept", content={"value": "create"})},
                        state="synthetic-other-state",
                    )
                ),
            )

        assert route.call_count == 0


class TestHowRegisterWiresTheQuestion:
    async def test_register_asks_before_it_writes(
        self, transport: httpx.AsyncClient, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folder(graph)
        route = _no_write(graph)
        mcp: FastMCP = FastMCP(name="wiring-under-test")
        creator.register(mcp, transport)
        tool = await mcp.get_tool(creator.TOOL_NAME)
        assert isinstance(tool, FunctionTool)

        first = cast(
            "DriveItemSummary | InputRequiredResult",
            await tool.fn(
                folder=_FOLDER_URI,
                name=_NAME,
                content=_CONTENT,
                ctx=_modern_context(),
                client=client,
            ),
        )

        _key, _state, _choices = _the_question(first)
        assert route.call_count == 0
