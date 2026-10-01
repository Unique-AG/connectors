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

from office_365_mcp.graph_client import GraphFailure, GraphForbidden, GraphNotFound
from office_365_mcp.shared.handles import (
    DriveFileHandle,
    DriveFolderHandle,
    MailMessageHandle,
    OnenotePageHandle,
    drive_item_handle,
)
from office_365_mcp.shared.notes import write_state_for
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Advised,
    Confirm,
    GraphAdviceMiddleware,
    ToolAdvice,
)
from office_365_mcp.tools import sharepoint_rename_item as renamer
from office_365_mcp.tools.sharepoint_rename_item import RenamedItem, a_person_agrees, rename_item

_DRIVE_ID = "b!SYNTHETICDRIVE0000"
_FILE_ID = "01SYNTHETICFILE0000"
_PARENT_ID = "01SYNTHETICPARENT0000"

_FILE_URI = DriveFileHandle(_DRIVE_ID, _FILE_ID).uri
_FOLDER_URI = DriveFolderHandle(_DRIVE_ID, _FILE_ID).uri

_ITEM_PATH = f"/drives/b%21SYNTHETICDRIVE0000/items/{_FILE_ID}"

_OLD_NAME = "Plan.docx"
_NEW_NAME = "Plan final.docx"

_PARENT: Mapping[str, object] = {
    "driveId": _DRIVE_ID,
    "driveType": "business",
    "id": _PARENT_ID,
    "name": "Reports",
    "path": "/drive/root:/Reports",
}


def _item_payload(
    *,
    name: str | None = _OLD_NAME,
    parent: Mapping[str, object] | None = _PARENT,
    folder: bool = False,
    root: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": _FILE_ID,
        "name": name,
        "size": 2048,
        "webUrl": "https://contoso.sharepoint.invalid/sites/finance/Reports/Plan.docx",
        "lastModifiedDateTime": "2026-09-01T08:00:00Z",
    }
    if parent is not None:
        payload["parentReference"] = dict(parent)
    if folder:
        payload["folder"] = {"childCount": 2}
    else:
        payload["file"] = {"mimeType": "application/octet-stream"}
    if root:
        payload["root"] = {}
    return payload


def _pre_reads(graph: respx.MockRouter, payload: Mapping[str, object]) -> respx.Route:
    return graph.get(_ITEM_PATH).mock(return_value=httpx.Response(200, json=dict(payload)))


def _patches(
    graph: respx.MockRouter, payload: Mapping[str, object] | None = None, *, status: int = 200
) -> respx.Route:
    answer = _item_payload(name=_NEW_NAME) if payload is None else dict(payload)
    return graph.patch(_ITEM_PATH).mock(return_value=httpx.Response(status, json=answer))


def _not_found() -> httpx.Response:
    return httpx.Response(404, json={"error": {"code": "itemNotFound", "message": "not found"}})


async def _agrees(question: str, about: str) -> str | None:
    assert question, "the person was asked nothing at all"
    assert about, "the answer was bound to nothing"
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return "The item was not renamed."


async def _rename(
    client: GraphServiceClient,
    *,
    item: str = _FILE_URI,
    name: str = _NEW_NAME,
    confirm: Confirm = _agrees,
) -> RenamedItem:
    answer = await rename_item(client, item=item, name=name, confirm=confirm)
    assert isinstance(answer, RenamedItem), "this call was answered with a question, not a rename"
    return answer


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


def _made(router: respx.MockRouter) -> Sequence[Call]:
    return cast("Sequence[Call]", router.calls)


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    renamer.register(mcp, transport)
    tool = await mcp.get_tool(renamer.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


async def _advised(client: GraphServiceClient) -> str:
    advice = GraphAdviceMiddleware(
        {
            renamer.TOOL_NAME: ToolAdvice(
                permissions=renamer.GRAPH_PERMISSIONS, not_found=renamer.GRAPH_NOT_FOUND
            )
        }
    )

    async def renames(context: MiddlewareContext[CallToolRequestParams]) -> ToolResult:
        _ = context
        _ = await _rename(client)
        raise AssertionError("the rename succeeded, so there is no advice to read")

    context = MiddlewareContext(message=CallToolRequestParams(name=renamer.TOOL_NAME, arguments={}))
    with pytest.raises(ToolError) as raised:
        _ = await advice.on_call_tool(context, renames)
    return str(raised.value)


class TestWhatItSendsToGraph:
    async def test_it_reads_the_item_then_patches_it_once_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        pre_read = _pre_reads(graph, _item_payload())
        patch = _patches(graph)

        _ = await _rename(client)

        assert [call.request.method for call in _made(graph)] == ["GET", "PATCH"]
        assert pre_read.call_count == 1
        assert patch.call_count == 1

    async def test_the_patch_body_carries_the_new_name_and_no_other_property(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _pre_reads(graph, _item_payload())
        patch = _patches(graph)

        _ = await _rename(client, name="Budget 2026.xlsx")

        sent = _sent(patch)
        assert sent["name"] == "Budget 2026.xlsx"
        assert set(sent) - {"@odata.type"} == {"name"}, f"the rename also sent {sorted(sent)}"

    async def test_the_patch_content_type_is_json(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _pre_reads(graph, _item_payload())
        patch = _patches(graph)

        _ = await _rename(client)

        assert patch.calls.last.request.headers["content-type"] == "application/json"

    async def test_a_folder_handle_patches_the_same_item_path(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _pre_reads(graph, _item_payload(name="Reports", folder=True))
        patch = _patches(graph, _item_payload(name="Reports 2026", folder=True))

        answer = await _rename(client, item=_FOLDER_URI, name="Reports 2026")

        assert patch.call_count == 1
        assert answer.item.is_folder

    async def test_the_pre_read_selects_the_item_fields_and_the_root_facet(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        pre_read = _pre_reads(graph, _item_payload())
        _ = _patches(graph)

        _ = await _rename(client)

        selected = pre_read.calls.last.request.url.params["$select"].split(",")
        assert "root" in selected
        assert "parentReference" in selected

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_503_on_the_patch_is_not_retried(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _pre_reads(graph, _item_payload())
        patch = graph.patch(_ITEM_PATH).mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(200, json=_item_payload(name=_NEW_NAME)),
            ]
        )

        with pytest.raises(GraphFailure):
            _ = await _rename(client)

        assert patch.call_count == 1, "the SDK sent the rename again on its own"


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            OnenotePageHandle("1-SYNTHETICPAGE00000000000000000000!ABCDEF").uri,
            MailMessageHandle("AAMkAGI2SYNTHETIC-mail-0001=").uri,
            _FILE_ID,
            _DRIVE_ID,
            "sharepoint:///files/01SYNTHETICFILE0000",
            "sharepoint:///items/b%21SYNTHETICDRIVE0000/01SYNTHETICFILE0000",
            "https://contoso.sharepoint.invalid/sites/finance/Shared%20Documents/Plan.docx",
            "/drive/root:/Reports/Plan.docx",
            "Plan.docx",
            "",
            "   ",
        ],
    )
    async def test_a_value_that_is_not_an_item_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError, match="takes a file handle or a folder handle"):
            _ = await _rename(client, item=value)

        assert len(graph.calls) == 0, "a refused handle renames nothing"

    async def test_the_handle_refusal_names_the_tools_that_mint_a_handle(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await _rename(client, item="Plan.docx")

        refusal = str(refused.value)
        assert "sharepoint_search_files" in refusal
        assert "sharepoint_browse_folder" in refusal
        assert refusal.endswith("This same value fails again, so do not retry it.")

    @pytest.mark.parametrize(
        ("item", "name", "reason"),
        [
            (_FILE_URI, "Q1/Q2.docx", "The name contains `/`."),
            (_FILE_URI, "Plan?.docx", "The name contains `?`."),
            (_FILE_URI, "~Plan.docx", "The name starts with `~`."),
            (_FILE_URI, "   ", "The name is empty or has only spaces in it."),
            (_FOLDER_URI, "Reports.", "The name ends with a period."),
        ],
        ids=["slash", "question-mark", "leading-tilde", "blank", "folder-trailing-period"],
    )
    async def test_a_name_onedrive_does_not_accept_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, item: str, name: str, reason: str
    ) -> None:
        with pytest.raises(ToolError, match="Nothing was changed") as refused:
            _ = await _rename(client, item=item, name=name)

        assert reason in str(refused.value)
        assert len(graph.calls) == 0, "a refused name renames nothing"

    async def test_a_file_name_that_ends_with_a_period_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _pre_reads(graph, _item_payload())
        patch = _patches(graph, _item_payload(name="Plan."))

        _ = await _rename(client, name="Plan.")

        assert patch.call_count == 1

    async def test_the_top_folder_of_a_drive_is_refused_after_the_read_and_nobody_is_asked(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        pre_read = _pre_reads(
            graph, _item_payload(name="root", parent=None, folder=True, root=True)
        )
        patch = _patches(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        with pytest.raises(ToolError, match="top folder of a drive") as refused:
            _ = await _rename(client, item=_FOLDER_URI, name="Everything", confirm=counting)

        assert "do not retry it" in str(refused.value)
        assert pre_read.call_count == 1
        assert patch.call_count == 0
        assert asked == [], "the person was asked about a rename this tool refuses"


class TestWhatItAnswers:
    async def test_the_answer_is_the_item_graph_sent_back_from_the_patch(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        pre_read = _pre_reads(graph, _item_payload())
        _ = _patches(graph, _item_payload(name=_NEW_NAME))

        answer = await _rename(client)

        assert answer.item.uri == _FILE_URI
        assert answer.item.name == _NEW_NAME
        assert answer.item.parent_uri == DriveFolderHandle(_DRIVE_ID, _PARENT_ID).uri
        assert answer.previous_name == _OLD_NAME
        assert pre_read.call_count == 1, "a patch answer with a drive id needs no re-read"

    async def test_the_previous_name_comes_from_the_pre_read_not_the_patch_answer(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _pre_reads(graph, _item_payload(name="Old plan.docx"))
        _ = _patches(graph, _item_payload(name=_NEW_NAME))

        answer = await _rename(client)

        assert answer.previous_name == "Old plan.docx"
        assert answer.item.name == _NEW_NAME

    async def test_the_previous_name_is_null_when_the_pre_read_named_none(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _pre_reads(graph, _item_payload(name=None))
        _ = _patches(graph)

        answer = await _rename(client)

        assert answer.previous_name is None

    async def test_a_patch_answer_with_no_drive_is_read_again_for_the_answer(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        reads = graph.get(_ITEM_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_item_payload()),
                httpx.Response(200, json=_item_payload(name=_NEW_NAME)),
            ]
        )
        patch = graph.patch(_ITEM_PATH).mock(
            return_value=httpx.Response(200, json={"id": _FILE_ID, "name": _NEW_NAME, "file": {}})
        )

        answer = await _rename(client)

        assert [call.request.method for call in _made(graph)] == ["GET", "PATCH", "GET"]
        assert patch.call_count == 1
        assert reads.call_count == 2
        assert answer.item.uri == _FILE_URI
        assert answer.item.name == _NEW_NAME


class TestGraphFailures:
    async def test_a_404_on_the_pre_read_is_a_not_found_and_nothing_is_patched(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(return_value=_not_found())
        patch = _patches(graph)

        with pytest.raises(GraphNotFound):
            _ = await _rename(client)

        assert patch.call_count == 0

    async def test_a_404_on_the_patch_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _pre_reads(graph, _item_payload())
        patch = graph.patch(_ITEM_PATH).mock(return_value=_not_found())

        with pytest.raises(GraphNotFound):
            _ = await _rename(client)

        assert patch.call_count == 1

    async def test_a_409_on_the_patch_reaches_the_model_as_the_shared_conflict_advice(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _pre_reads(graph, _item_payload())
        _ = graph.patch(_ITEM_PATH).mock(
            return_value=httpx.Response(
                409, json={"error": {"code": "nameAlreadyExists", "message": "Name already exists"}}
            )
        )

        message = await _advised(client)

        assert "an item that is already there prevents it" in message
        assert "Change the name" in message
        assert "Graph error code nameAlreadyExists" in message
        assert "bad request" not in message

    async def test_a_403_on_the_patch_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _pre_reads(graph, _item_payload())
        _ = graph.patch(_ITEM_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _rename(client)

    async def test_a_failed_re_read_is_reported_as_a_rename_that_happened(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(
            side_effect=[httpx.Response(200, json=_item_payload()), _not_found()]
        )
        patch = graph.patch(_ITEM_PATH).mock(
            return_value=httpx.Response(200, json={"id": _FILE_ID, "name": _NEW_NAME, "file": {}})
        )

        with pytest.raises(Advised, match="Microsoft 365 renamed the item.") as raised:
            _ = await _rename(client)

        assert isinstance(raised.value.__cause__, GraphNotFound)
        assert patch.call_count == 1

    async def test_the_advice_layer_keeps_a_rename_that_happened_word_for_word(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(
            side_effect=[httpx.Response(200, json=_item_payload()), _not_found()]
        )
        _ = graph.patch(_ITEM_PATH).mock(
            return_value=httpx.Response(200, json={"id": _FILE_ID, "name": _NEW_NAME, "file": {}})
        )

        message = await _advised(client)

        assert message.startswith("Microsoft 365 renamed the item.")
        assert "nothing was renamed" not in message, (
            "the 404 advice replaced a rename that happened"
        )

    async def test_a_re_read_with_no_drive_is_also_reported_as_a_rename_that_happened(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_item_payload()),
                httpx.Response(200, json=_item_payload(name=_NEW_NAME, parent=None)),
            ]
        )
        _ = graph.patch(_ITEM_PATH).mock(
            return_value=httpx.Response(200, json={"id": _FILE_ID, "name": _NEW_NAME, "file": {}})
        )

        with pytest.raises(Advised, match="Microsoft 365 renamed the item."):
            _ = await _rename(client)

    async def test_the_call_example_reaches_graph_and_the_pre_read_is_what_a_403_refuses(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        example = cast("Mapping[str, str]", renamer.GRAPH_CALL_EXAMPLE)
        handle = drive_item_handle(example["item"])
        assert handle is not None, "GRAPH_CALL_EXAMPLE's own item value is not an item handle"
        refused = graph.get(f"/drives/b%21SYNTHETICDRIVE0000/items/{handle.item_id}").mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _rename(client, item=example["item"], name=example["name"])

        assert refused.call_count == 1

    def test_not_found_advice_says_nothing_was_renamed_and_points_at_the_listers(self) -> None:
        assert "nothing was renamed" in renamer.GRAPH_NOT_FOUND
        assert "sharepoint_search_files" in renamer.GRAPH_NOT_FOUND
        assert "sharepoint_browse_folder" in renamer.GRAPH_NOT_FOUND


class TestThePersonBetweenTheRenameAndTheFolder:
    async def test_every_rename_is_asked_about_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _pre_reads(graph, _item_payload())
        patch = _patches(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _rename(client, confirm=counting)

        assert len(asked) == 1
        assert patch.call_count == 1

    async def test_a_refusal_renames_nothing_and_says_so(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        pre_read = _pre_reads(graph, _item_payload())
        patch = _patches(graph)

        with pytest.raises(ToolError, match="The item was not renamed"):
            _ = await _rename(client, confirm=_refuses)

        assert patch.call_count == 0
        assert pre_read.call_count == 1

    async def test_the_question_names_the_old_and_new_names_and_the_folder(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _pre_reads(graph, _item_payload())
        _ = _patches(graph)
        asked: list[str] = []
        bound: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            asked.append(question)
            bound.append(about)
            return None

        _ = await _rename(client, confirm=capturing)

        assert asked == ["Rename 'Plan.docx' to 'Plan final.docx' in the folder 'Reports'?"]
        assert bound == [write_state_for(renamer.TOOL_NAME, _DRIVE_ID, _FILE_ID, _NEW_NAME)]

    async def test_the_question_names_no_item_or_folder_graph_left_unnamed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _pre_reads(graph, _item_payload(name=None, parent={"driveId": _DRIVE_ID}))
        _ = _patches(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _rename(client, confirm=capturing)

        assert "an unnamed item" in asked[0]
        assert "an unnamed folder" in asked[0]

    async def test_about_is_the_same_for_two_identical_calls_and_different_for_another_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _pre_reads(graph, _item_payload())
        _ = _patches(graph)
        bound: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert question
            bound.append(about)
            return None

        _ = await _rename(client, name="Same.docx", confirm=capturing)
        _ = await _rename(client, name="Same.docx", confirm=capturing)
        _ = await _rename(client, name="Other.docx", confirm=capturing)

        assert bound[0] == bound[1]
        assert bound[2] != bound[0]

    @pytest.mark.parametrize(
        "answer",
        [
            DeclinedElicitation(),
            CancelledElicitation(),
            AcceptedElicitation(data="do not rename"),
            MCPError(METHOD_NOT_FOUND, "Method not found"),
            ToolError("the client refused the request"),
        ],
        ids=["declined", "cancelled", "another-answer", "cannot-ask", "client-error"],
    )
    async def test_every_answer_but_agreement_is_a_refusal(self, answer: object) -> None:
        confirm = a_person_agrees(_context(answer))

        refusal = await confirm("Rename 'Plan.docx' to 'Plan final.docx'?", "synthetic-state")

        assert isinstance(refusal, str)
        assert refusal

    async def test_a_refusal_this_tool_words_opens_by_saying_the_item_was_not_renamed(
        self,
    ) -> None:
        confirm = a_person_agrees(_context(DeclinedElicitation()))

        refusal = await confirm("Rename 'Plan.docx' to 'Plan final.docx'?", "synthetic-state")

        assert isinstance(refusal, str)
        assert refusal.startswith("The item was not renamed.")

    async def test_agreeing_answers_with_no_refusal(self) -> None:
        confirm = a_person_agrees(_context(AcceptedElicitation(data="rename")))

        assert await confirm("Rename 'Plan.docx' to 'Plan final.docx'?", "synthetic-state") is None


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
    async def test_the_first_round_asks_and_never_reaches_the_write(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _pre_reads(graph, _item_payload())
        patch = _patches(graph)

        answer = await rename_item(
            client, item=_FILE_URI, name=_NEW_NAME, confirm=a_person_agrees(_modern_context())
        )

        assert isinstance(answer, InputRequiredResult)
        assert answer.request_state == write_state_for(
            renamer.TOOL_NAME, _DRIVE_ID, _FILE_ID, _NEW_NAME
        )
        assert patch.call_count == 0

    async def test_the_first_round_asks_the_question_this_tool_words(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _pre_reads(graph, _item_payload())
        _ = _patches(graph)

        answer = await rename_item(
            client, item=_FILE_URI, name=_NEW_NAME, confirm=a_person_agrees(_modern_context())
        )

        assert isinstance(answer, InputRequiredResult)
        requests = answer.input_requests or {}
        request = requests[next(iter(requests))]
        assert isinstance(request, ElicitRequest)
        params = request.params
        assert isinstance(params, ElicitRequestFormParams)
        assert params.message == "Rename 'Plan.docx' to 'Plan final.docx' in the folder 'Reports'?"

    async def test_the_second_round_renames_under_the_state_it_was_agreed_to_by(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _pre_reads(graph, _item_payload())
        patch = _patches(graph)

        first = await rename_item(
            client, item=_FILE_URI, name=_NEW_NAME, confirm=a_person_agrees(_modern_context())
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))

        answer = await rename_item(
            client,
            item=_FILE_URI,
            name=_NEW_NAME,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": "rename"})},
                    state=first.request_state,
                )
            ),
        )

        assert isinstance(answer, RenamedItem)
        assert patch.call_count == 1

    async def test_an_answer_bound_to_another_name_renames_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _pre_reads(graph, _item_payload())
        patch = _patches(graph)

        first = await rename_item(
            client, item=_FILE_URI, name=_NEW_NAME, confirm=a_person_agrees(_modern_context())
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await rename_item(
                client,
                item=_FILE_URI,
                name="Another name.docx",
                confirm=a_person_agrees(
                    _modern_context(
                        answers={key: ElicitResult(action="accept", content={"value": "rename"})},
                        state=first.request_state,
                    )
                ),
            )

        assert patch.call_count == 0

    async def test_a_decline_in_the_second_round_renames_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _pre_reads(graph, _item_payload())
        patch = _patches(graph)

        first = await rename_item(
            client, item=_FILE_URI, name=_NEW_NAME, confirm=a_person_agrees(_modern_context())
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))

        with pytest.raises(ToolError, match="The item was not renamed"):
            _ = await rename_item(
                client,
                item=_FILE_URI,
                name=_NEW_NAME,
                confirm=a_person_agrees(
                    _modern_context(
                        answers={key: ElicitResult(action="decline")}, state=first.request_state
                    )
                ),
            )

        assert patch.call_count == 0


class TestTheClientThatCannotAsk:
    async def test_a_client_that_cannot_ask_renames_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _pre_reads(graph, _item_payload())
        patch = _patches(graph)

        with pytest.raises(ToolError, match="does not support elicitation"):
            _ = await rename_item(
                client,
                item=_FILE_URI,
                name=_NEW_NAME,
                confirm=a_person_agrees(_context(MCPError(METHOD_NOT_FOUND, "Method not found"))),
            )

        assert patch.call_count == 0


class TestHowItDeclaresItself:
    def test_the_permission_is_files_readwrite_all(self) -> None:
        assert renamer.GRAPH_PERMISSIONS == ("Files.ReadWrite.All",)

    def test_the_call_example_is_a_file_handle_and_a_usable_name(self) -> None:
        example = cast("Mapping[str, str]", renamer.GRAPH_CALL_EXAMPLE)

        assert set(example) == {"item", "name"}
        assert isinstance(drive_item_handle(example["item"]), DriveFileHandle)

    async def test_it_takes_two_arguments_and_no_others(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])

        assert set(properties) == {"item", "name"}
        assert set(cast("list[str]", parameters["required"])) == {"item", "name"}

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
        assert annotations is not None
        assert tool.title == "Rename an Item"
        assert annotations.read_only_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["idempotentHint"]

    async def test_the_answer_publishes_the_item_and_the_previous_name(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        schema = cast("Mapping[str, Mapping[str, object]]", tool.output_schema)
        assert set(schema["properties"]) == {"item", "previous_name"}

    async def test_the_description_says_the_canonical_sentences_word_for_word(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "This tool asks the user to agree before it changes anything, every time." in (
            description
        )
        assert (
            "OneDrive and SharePoint can show the change to everyone who can open the folder."
            in (description)
        )
        assert "This call is safe to repeat after a timeout." in description

    async def test_the_description_says_what_it_changes_and_where_the_handle_comes_from(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "Changes the name of one file or folder" in description
        assert "stays in the same folder" in description
        assert "sharepoint_search_files" in description
        assert "sharepoint_browse_folder" in description
        assert "Write the extension in `name`, for example `Plan.docx`." in description
        assert "A name without it changes how the file opens." in description

    async def test_the_description_keeps_the_house_shape(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        lead, notes = description.split("\n\nNotes:\n")
        bullets = [line for line in notes.splitlines() if line.startswith("- ")]
        assert lead.endswith(
            "OneDrive and SharePoint can show the change to everyone who can open the folder."
        )
        assert 1 <= len(bullets) <= 3
        assert 45 <= len(description.split()) <= 210

    @pytest.mark.parametrize("argument", ["item", "name"])
    async def test_each_argument_is_described_in_15_to_60_words(
        self, transport: httpx.AsyncClient, argument: str
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])

        words = len(str(properties[argument]["description"]).split())
        assert 15 <= words <= 60, f"{argument} is described in {words} words"
