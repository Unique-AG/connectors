import inspect
from collections.abc import Mapping, Sequence
from typing import cast
from urllib.parse import quote

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
from mcp.shared.exceptions import MCPError
from mcp.types import (
    METHOD_NOT_FOUND,
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
    DriveFileHandle,
    DriveFolderHandle,
    drive_item_handle,
)
from office_365_mcp.shared.notes import write_state_for
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE_IDEMPOTENT, Confirm
from office_365_mcp.tools import sharepoint_delete_item as deleter
from office_365_mcp.tools.sharepoint_delete_item import DeletedItem, a_person_agrees, delete_item

_DRIVE_ID = "b!SYNTHETICDRIVE0000"
_ITEM_ID = "01SYNTHETICFILE0000"
_PARENT_ID = "01SYNTHETICPARENT0000"

_FILE_URI = DriveFileHandle(_DRIVE_ID, _ITEM_ID).uri
_FOLDER_URI = DriveFolderHandle(_DRIVE_ID, _ITEM_ID).uri
_PARENT_URI = DriveFolderHandle(_DRIVE_ID, _PARENT_ID).uri

_ITEM_PATH = "/drives/b%21SYNTHETICDRIVE0000/items/01SYNTHETICFILE0000"

_ITEM_ROUTE = f"/v1.0/drives/{_DRIVE_ID}/items/{_ITEM_ID}"

_NAME = "Quarterly-report.docx"

_PARENT: Mapping[str, object] = {
    "driveId": _DRIVE_ID,
    "id": _PARENT_ID,
    "path": "/drive/root:/Reports/Q1%202026",
}

_NOT_FOUND = {"error": {"code": "itemNotFound", "message": "not found"}}

_DENIED = {"error": {"code": "accessDenied", "message": "denied"}}


def _item_payload(
    *,
    name: str | None = _NAME,
    parent: Mapping[str, object] | None = _PARENT,
    child_count: int | None = None,
    a_folder: bool = False,
    the_root: bool = False,
) -> dict[str, object]:
    facet: dict[str, object] = (
        {"folder": {} if child_count is None else {"childCount": child_count}}
        if a_folder
        else {"file": {"mimeType": "application/octet-stream"}}
    )
    return {
        "id": _ITEM_ID,
        "name": name,
        "parentReference": dict(parent) if parent is not None else None,
        **facet,
        **({"root": {}} if the_root else {}),
    }


def _reads(graph: respx.MockRouter, payload: Mapping[str, object]) -> respx.Route:
    return graph.get(_ITEM_PATH).mock(return_value=httpx.Response(200, json=dict(payload)))


def _deletes(graph: respx.MockRouter, *, status: int = 204) -> respx.Route:
    return graph.delete(_ITEM_PATH).mock(return_value=httpx.Response(status))


async def _agrees(question: str, about: str) -> str | None:
    assert question, "the person was asked nothing at all"
    assert about, "the answer was bound to nothing"
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return "The item was not moved to the recycle bin."


async def _delete(
    client: GraphServiceClient, *, item: str = _FILE_URI, confirm: Confirm = _agrees
) -> DeletedItem:
    answer = await delete_item(client, item=item, confirm=confirm)
    assert isinstance(answer, DeletedItem), "this call was answered with a question, not a delete"
    return answer


async def _asked(client: GraphServiceClient, *, item: str = _FILE_URI) -> list[str]:
    asked: list[str] = []

    async def capturing(question: str, about: str) -> str | None:
        assert about
        asked.append(question)
        return None

    _ = await _delete(client, item=item, confirm=capturing)
    return asked


def _made(route: respx.MockRouter | respx.Route) -> Sequence[Call]:
    return cast("Sequence[Call]", route.calls)


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    deleter.register(mcp, transport)
    tool = await mcp.get_tool(deleter.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestWhatItSendsToGraph:
    async def test_it_reads_the_item_then_deletes_it_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item_payload())
        _ = _deletes(graph)

        _ = await _delete(client)

        made = _made(graph)
        assert [call.request.method for call in made] == ["GET", "DELETE"]
        assert [call.request.url.path for call in made] == [_ITEM_ROUTE, _ITEM_ROUTE]

    async def test_a_folder_is_deleted_at_the_same_item_path(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item_payload(a_folder=True, child_count=3))
        delete_route = _deletes(graph)

        answer = await _delete(client, item=_FOLDER_URI)

        assert delete_route.call_count == 1
        assert answer.was_folder is True

    async def test_the_pre_read_selects_the_item_fields_and_the_root_facet(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read_route = _reads(graph, _item_payload())
        _ = _deletes(graph)

        _ = await _delete(client)

        selected = read_route.calls.last.request.url.params["$select"].split(",")
        assert {"root", "folder", "parentReference", "name"} <= set(selected)

    async def test_the_delete_carries_no_body_no_if_match_and_no_prefer(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item_payload())
        delete_route = _deletes(graph)

        _ = await _delete(client)

        request = delete_route.calls.last.request
        assert request.content == b""
        assert "if-match" not in request.headers
        assert "prefer" not in request.headers

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_503_on_the_delete_is_not_retried(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item_payload())
        delete_route = graph.delete(_ITEM_PATH).mock(
            side_effect=[httpx.Response(503), httpx.Response(204)]
        )

        with pytest.raises(GraphUnavailable):
            _ = await _delete(client)

        assert delete_route.call_count == 1, "the SDK sent the delete again on its own"


class TestTheConnectorNeverErases:
    def test_the_module_never_names_the_permanent_delete_of_graph(self) -> None:
        source = inspect.getsource(deleter)

        assert "def delete_item" in source, "this guard reads a module that is not the tool"
        assert "permanent_delete" not in source
        assert "permanentDelete" not in source


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            "sharepoint:///files/b%21SYNTHETICDRIVE0000",
            "01SYNTHETICFILE0000",
            "https://contoso.sharepoint.invalid/sites/finance/Shared-Documents/Quarterly.docx",
            _NAME,
            "",
            "   ",
            "sharepoint:///files//01SYNTHETICFILE0000",
            "sharepoint:///folders/%20/01SYNTHETICFILE0000",
            "onenote:///pages/1-SYNTHETICPAGE",
        ],
    )
    async def test_a_value_that_is_not_an_item_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError):
            _ = await _delete(client, item=value)

        assert len(graph.calls) == 0, "a refused handle deletes nothing"

    async def test_the_handle_refusal_names_the_tools_that_mint_a_handle(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await _delete(client, item=_NAME)

        assert "sharepoint_browse_folder" in str(refused.value)
        assert "sharepoint_search_files" in str(refused.value)
        assert "The item was not moved to the recycle bin." in str(refused.value)

    async def test_the_top_folder_of_a_drive_is_refused_after_the_read_and_nobody_is_asked(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read_route = _reads(graph, _item_payload(a_folder=True, parent=None, the_root=True))
        delete_route = _deletes(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        with pytest.raises(ToolError, match="top folder of a drive"):
            _ = await delete_item(client, item=_FOLDER_URI, confirm=counting)

        assert read_route.call_count == 1
        assert asked == []
        assert delete_route.call_count == 0


class TestWhatItAnswers:
    async def test_the_answer_names_the_item_and_the_folder_that_held_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item_payload())
        _ = _deletes(graph)

        answer = await _delete(client)

        assert answer.name == _NAME
        assert answer.parent_uri == _PARENT_URI
        assert answer.was_folder is False
        assert answer.deleted is True

    async def test_nulls_when_graph_names_no_item_name_and_no_parent(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item_payload(name=None, parent=None))
        _ = _deletes(graph)

        answer = await _delete(client)

        assert answer.name is None
        assert answer.parent_uri is None
        assert answer.deleted is True


class TestGraphFailures:
    async def test_a_404_on_the_pre_read_is_a_not_found_and_nothing_is_deleted(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read_route = graph.get(_ITEM_PATH).mock(return_value=httpx.Response(404, json=_NOT_FOUND))
        delete_route = _deletes(graph)

        with pytest.raises(GraphNotFound):
            _ = await _delete(client)

        assert read_route.call_count == 1
        assert delete_route.call_count == 0, "the pre-read failed before anything was deleted"

    async def test_a_404_on_the_delete_after_the_agreement_answers_that_the_item_is_gone(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item_payload())
        delete_route = graph.delete(_ITEM_PATH).mock(
            return_value=httpx.Response(404, json=_NOT_FOUND)
        )

        answer = await _delete(client)

        assert delete_route.call_count == 1
        assert answer.deleted is True
        assert answer.name == _NAME

    async def test_a_403_on_the_delete_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item_payload())
        _ = graph.delete(_ITEM_PATH).mock(return_value=httpx.Response(403, json=_DENIED))

        with pytest.raises(GraphForbidden):
            _ = await _delete(client)

    async def test_the_call_example_reaches_graph_and_the_pre_read_is_what_a_403_refuses(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        example = cast("Mapping[str, str]", deleter.GRAPH_CALL_EXAMPLE)
        handle = drive_item_handle(example["item"])
        assert handle is not None, "GRAPH_CALL_EXAMPLE's own item value is not an item handle"
        refused = graph.get(
            f"/drives/{quote(handle.drive_id, safe='')}/items/{quote(handle.item_id, safe='')}"
        ).mock(return_value=httpx.Response(403, json=_DENIED))

        with pytest.raises(GraphForbidden):
            _ = await _delete(client, item=example["item"])

        assert refused.call_count == 1

    def test_not_found_advice_says_nothing_was_deleted_and_points_at_the_listers(self) -> None:
        assert "deleted nothing" in deleter.GRAPH_NOT_FOUND
        assert "already gone" in deleter.GRAPH_NOT_FOUND
        assert "sharepoint_browse_folder" in deleter.GRAPH_NOT_FOUND
        assert "sharepoint_search_files" in deleter.GRAPH_NOT_FOUND


class TestConfirmationIsAlwaysAsked:
    async def test_every_delete_is_asked_about_once_and_before_the_delete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item_payload())
        delete_route = _deletes(graph)
        deletes_when_asked: list[int] = []

        async def counting(question: str, about: str) -> str | None:
            assert question
            assert about
            deletes_when_asked.append(delete_route.call_count)
            return None

        _ = await _delete(client, confirm=counting)

        assert deletes_when_asked == [0], "a delete must always be agreed to before it is sent"
        assert delete_route.call_count == 1

    async def test_a_refusal_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read_route = _reads(graph, _item_payload())
        delete_route = _deletes(graph)

        with pytest.raises(ToolError, match="The item was not moved to the recycle bin"):
            _ = await delete_item(client, item=_FILE_URI, confirm=_refuses)

        assert delete_route.call_count == 0
        assert read_route.call_count == 1

    async def test_the_question_names_the_file_its_folder_and_the_recycle_bin(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item_payload())
        _ = _deletes(graph)
        bound: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert question == (
                f"Move the file {_NAME!r} from 'Reports/Q1 2026' to the recycle bin?"
            )
            bound.append(about)
            return None

        _ = await _delete(client, confirm=capturing)

        assert bound == [write_state_for(deleter.TOOL_NAME, _DRIVE_ID, _ITEM_ID)]

    @pytest.mark.parametrize(
        ("child_count", "said"),
        [
            (3, " It has 3 items directly inside it."),
            (1, " It has 1 item directly inside it."),
            (0, " The folder is empty."),
            (None, ""),
        ],
    )
    async def test_a_folder_question_says_everything_inside_goes_too_and_how_much(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        child_count: int | None,
        said: str,
    ) -> None:
        _ = _reads(graph, _item_payload(name="Q1", a_folder=True, child_count=child_count))
        _ = _deletes(graph)

        asked = await _asked(client, item=_FOLDER_URI)

        assert asked == [
            "Move the folder 'Q1' from 'Reports/Q1 2026' to the recycle bin, together with "
            + f"everything inside it?{said}"
        ]

    async def test_an_item_at_the_top_of_a_drive_is_asked_about_by_that_place(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item_payload(parent={**_PARENT, "path": "/drive/root:"}))
        _ = _deletes(graph)

        asked = await _asked(client)

        assert asked == [f"Move the file {_NAME!r} from the top of the drive to the recycle bin?"]

    async def test_the_question_names_no_item_or_folder_that_graph_left_unnamed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item_payload(name=None, parent=None))
        _ = _deletes(graph)

        asked = await _asked(client)

        assert asked == ["Move the file 'an item with no name' from its folder to the recycle bin?"]

    @pytest.mark.parametrize(
        "answer",
        [
            DeclinedElicitation(),
            CancelledElicitation(),
            AcceptedElicitation(data="keep the item"),
            MCPError(METHOD_NOT_FOUND, "Method not found"),
            ToolError("the client refused the request"),
        ],
        ids=["declined", "cancelled", "another-answer", "cannot-ask", "client-error"],
    )
    async def test_every_answer_but_agreement_is_a_refusal(self, answer: object) -> None:
        confirm = a_person_agrees(_context(answer))

        refusal = await confirm("Move the file 'Q1.docx' to the recycle bin?", "synthetic-state")

        assert isinstance(refusal, str)
        assert refusal

    async def test_a_refusal_this_tool_words_opens_by_saying_nothing_was_moved(self) -> None:
        confirm = a_person_agrees(_context(DeclinedElicitation()))

        refusal = await confirm("Move the file 'Q1.docx' to the recycle bin?", "synthetic-state")

        assert isinstance(refusal, str)
        assert refusal.startswith("The item was not moved to the recycle bin.")

    async def test_agreeing_answers_with_no_refusal(self) -> None:
        confirm = a_person_agrees(_context(AcceptedElicitation(data="delete")))

        assert await confirm("Move the file 'Q1.docx'?", "synthetic-state") is None


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
        _ = _reads(graph, _item_payload())
        delete_route = _deletes(graph)

        answer = await delete_item(
            client, item=_FILE_URI, confirm=a_person_agrees(_modern_context())
        )

        assert isinstance(answer, InputRequiredResult)
        assert answer.request_state == write_state_for(deleter.TOOL_NAME, _DRIVE_ID, _ITEM_ID)
        requests = answer.input_requests or {}
        request = requests[next(iter(requests))]
        assert isinstance(request, ElicitRequest)
        params = request.params
        assert isinstance(params, ElicitRequestFormParams)
        assert _NAME in params.message
        assert delete_route.call_count == 0

    async def test_the_second_round_deletes_under_the_ids_it_was_agreed_to_by(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item_payload())
        delete_route = _deletes(graph)
        state = write_state_for(deleter.TOOL_NAME, _DRIVE_ID, _ITEM_ID)

        first = await delete_item(
            client, item=_FILE_URI, confirm=a_person_agrees(_modern_context())
        )
        assert isinstance(first, InputRequiredResult)
        key = next(iter(first.input_requests or {}))

        answer = await delete_item(
            client,
            item=_FILE_URI,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": "delete"})},
                    state=state,
                )
            ),
        )

        assert isinstance(answer, DeletedItem)
        assert delete_route.call_count == 1

    async def test_an_answer_bound_to_another_item_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item_payload())
        delete_route = _deletes(graph)

        first = await delete_item(
            client, item=_FILE_URI, confirm=a_person_agrees(_modern_context())
        )
        assert isinstance(first, InputRequiredResult)
        key = next(iter(first.input_requests or {}))

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await delete_item(
                client,
                item=_FILE_URI,
                confirm=a_person_agrees(
                    _modern_context(
                        answers={key: ElicitResult(action="accept", content={"value": "delete"})},
                        state=write_state_for(deleter.TOOL_NAME, _DRIVE_ID, _PARENT_ID),
                    )
                ),
            )

        assert delete_route.call_count == 0

    async def test_a_decline_in_the_second_round_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item_payload())
        delete_route = _deletes(graph)
        state = write_state_for(deleter.TOOL_NAME, _DRIVE_ID, _ITEM_ID)

        first = await delete_item(
            client, item=_FILE_URI, confirm=a_person_agrees(_modern_context())
        )
        assert isinstance(first, InputRequiredResult)
        key = next(iter(first.input_requests or {}))

        with pytest.raises(ToolError, match="The item was not moved to the recycle bin"):
            _ = await delete_item(
                client,
                item=_FILE_URI,
                confirm=a_person_agrees(
                    _modern_context(
                        answers={
                            key: ElicitResult(action="accept", content={"value": "keep the item"})
                        },
                        state=state,
                    )
                ),
            )

        assert delete_route.call_count == 0

    async def test_a_second_call_after_the_item_is_gone_reports_not_found_and_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read_route = graph.get(_ITEM_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_item_payload()),
                httpx.Response(404, json=_NOT_FOUND),
            ]
        )
        delete_route = _deletes(graph)

        _ = await _delete(client)
        with pytest.raises(GraphNotFound):
            _ = await _delete(client)

        assert read_route.call_count == 2
        assert delete_route.call_count == 1


class TestTheClientThatCannotAsk:
    async def test_a_client_that_cannot_ask_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item_payload())
        delete_route = _deletes(graph)

        class _CannotAsk:
            request_context: object = None

            async def elicit(self, message: str, response_type: object = None) -> object:
                assert message and response_type is not None
                raise MCPError(METHOD_NOT_FOUND, "Method not found")

        confirm = a_person_agrees(cast("Context", cast("object", _CannotAsk())))

        with pytest.raises(ToolError, match="does not support elicitation"):
            _ = await delete_item(client, item=_FILE_URI, confirm=confirm)

        assert delete_route.call_count == 0


class TestHowItDeclaresItself:
    def test_the_permission_is_files_readwrite_all(self) -> None:
        assert deleter.GRAPH_PERMISSIONS == ("Files.ReadWrite.All",)

    def test_the_call_example_is_an_item_handle_and_nothing_else(self) -> None:
        example = cast("Mapping[str, str]", deleter.GRAPH_CALL_EXAMPLE)

        assert set(example) == {"item"}
        assert drive_item_handle(example["item"]) is not None

    async def test_it_takes_one_argument_and_no_others(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])

        assert set(properties) == {"item"}
        assert cast("list[str]", parameters["required"]) == ["item"]

    @pytest.mark.parametrize("word", ["client", "ctx", "context", "token", "graph"])
    async def test_no_wiring_of_this_server_is_published_as_an_argument(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_it_announces_itself_as_a_destructive_idempotent_write(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None, (
            "a tool with no annotations joins the write surface by omission"
        )
        assert tool.title == "Delete an Item"
        assert annotations.read_only_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["idempotentHint"]
        assert not hasattr(deleter, "CHANGE_SHOWN_BY")

    async def test_the_answer_publishes_the_item_its_folder_and_what_it_was(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        schema = cast("Mapping[str, Mapping[str, object]]", tool.output_schema)
        assert set(schema["properties"]) == {"name", "parent_uri", "was_folder", "deleted"}

    async def test_the_description_says_the_canonical_sentences_word_for_word(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        lead = description.split("\n\nNotes:\n")[0]
        assert "This tool asks the user to agree before it changes anything, every time." in (
            description
        )
        assert lead.endswith(
            "OneDrive and SharePoint can show the change to everyone who can open the folder."
        )
        assert "This call is safe to repeat after a timeout." in description

    async def test_the_description_says_it_uses_the_recycle_bin_and_never_erases(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "to the recycle bin" in description
        assert "together with everything inside it" in description
        assert "this connector never erases a file or a folder permanently" in (
            description.casefold()
        )
        assert "top folder of a drive" in description
        assert "sharepoint_browse_folder" in description
        assert "sharepoint_search_files" in description

    async def test_the_description_keeps_the_house_shape(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        lead, notes = description.split("\n\nNotes:\n")
        bullets = [line for line in notes.splitlines() if line.startswith("- ")]
        assert lead
        assert 1 <= len(bullets) <= 3
        assert 45 <= len(description.split()) <= 210

    async def test_the_argument_is_described_in_15_to_60_words(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])

        words = len(str(properties["item"]["description"]).split())
        assert 15 <= words <= 60, f"item is described in {words} words"
