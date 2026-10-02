import json
from collections.abc import Mapping
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
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

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound, GraphUnavailable
from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    OnenoteOperationHandle,
    OnenoteOwner,
    OnenoteSectionGroupHandle,
    OnenoteSectionHandle,
    onenote_notebook_handle,
)
from office_365_mcp.shared.notes import OperationSummary, write_state_for
from office_365_mcp.shared.seam import WRITE_ADDITIVE, Advised, Confirm
from office_365_mcp.tools import onenote_copy_notebook as copier
from office_365_mcp.tools.onenote_copy_notebook import a_person_agrees, copy_notebook

_NOTEBOOK_ID = "1-SYNTHETICNOTEBOOK0000!0-ABCDEF"
_OPERATION_ID = "1-SYNTHETICOPERATION0000!0-ABCDEF"
_GROUP_ID = "5c6b7a81-2f0d-4a24-9b1e-8a9c3c470f9e"
_SOURCE_GROUP_ID = "0f9e8a9c-3c47-4a24-9b1e-5c6b7a812f0d"

_NOTEBOOK_URI = OnenoteNotebookHandle(_NOTEBOOK_ID).uri
_GROUP_NOTEBOOK_URI = OnenoteNotebookHandle(
    _NOTEBOOK_ID, owner=OnenoteOwner("groups", _SOURCE_GROUP_ID)
).uri

_COPY_PATH = f"/me/onenote/notebooks/{_NOTEBOOK_ID}/copyNotebook"
_NOTEBOOK_GET_PATH = f"/me/onenote/notebooks/{_NOTEBOOK_ID}"
_SOURCE_GROUP_ROOT = f"/groups/{_SOURCE_GROUP_ID}/onenote"

_SITE_ID = (
    "contoso.sharepoint.invalid,0d1e2f3a-0000-4000-8000-000000000001,"
    + "4b5c6d7e-0000-4000-8000-000000000002"
)
_SITE = OnenoteOwner("sites", _SITE_ID)
_SITE_NOTEBOOK_URI = OnenoteNotebookHandle(_NOTEBOOK_ID, owner=_SITE).uri


def _operation_payload(
    *,
    operation_id: str | None = _OPERATION_ID,
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


def _operation_location(operation_id: str = _OPERATION_ID) -> str:
    return f"https://graph.microsoft.com/v1.0/me/onenote/operations/{operation_id}"


def _copies_with_body(
    graph: respx.MockRouter, *, status: int = 202, payload: Mapping[str, object] | None = None
) -> respx.Route:
    body = dict(payload) if payload is not None else _operation_payload()
    return graph.post(_COPY_PATH).mock(return_value=httpx.Response(status, json=body))


def _copies_with_header_only(
    graph: respx.MockRouter, *, status: int = 202, operation_id: str = _OPERATION_ID
) -> respx.Route:
    return graph.post(_COPY_PATH).mock(
        return_value=httpx.Response(
            status, content=b"", headers={"Operation-Location": _operation_location(operation_id)}
        )
    )


def _notebook_route(
    graph: respx.MockRouter, *, path: str = _NOTEBOOK_GET_PATH, name: str | None = "Work"
) -> respx.Route:
    return graph.get(path).mock(
        return_value=httpx.Response(
            200,
            json={"id": _NOTEBOOK_ID, "displayName": name, "isShared": False, "userRole": "Owner"},
        )
    )


async def _never_asked(question: str, about: str) -> str | None:
    raise AssertionError(f"a copy into the user's own OneDrive asked {question!r} for {about!r}")


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
    notebook: str = _NOTEBOOK_URI,
    new_name: str | None = None,
    to_group: str | None = None,
    confirm: Confirm = _never_asked,
) -> OperationSummary:
    answer = await copy_notebook(
        client, notebook=notebook, new_name=new_name, to_group=to_group, confirm=confirm
    )
    assert isinstance(answer, OperationSummary), (
        "this call was answered with a question, not an operation"
    )
    return answer


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    copier.register(mcp, transport)
    tool = await mcp.get_tool(copier.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestWhatItSendsToGraph:
    async def test_it_copies_the_notebook_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copy = _copies_with_header_only(graph)

        _ = await _copy(client)

        assert copy.call_count == 1
        assert len(graph.calls) == 1

    async def test_an_empty_body_is_sent_when_no_name_is_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copy = _copies_with_header_only(graph)

        _ = await _copy(client)

        assert _sent(copy) == {}

    async def test_a_new_name_is_sent_as_rename_as(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copy = _copies_with_header_only(graph)

        _ = await _copy(client, new_name="Renamed notebook")

        assert _sent(copy) == {"renameAs": "Renamed notebook"}

    async def test_no_group_site_or_folder_keys_are_sent_without_to_group(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copy = _copies_with_header_only(graph)

        _ = await _copy(client, new_name="Renamed notebook")

        sent = _sent(copy)
        assert "groupId" not in sent
        assert "siteId" not in sent
        assert "siteCollectionId" not in sent
        assert "notebookFolder" not in sent

    async def test_the_copy_content_type_is_json(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copy = _copies_with_header_only(graph)

        _ = await _copy(client)

        assert copy.calls.last.request.headers["content-type"] == "application/json"

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_copy_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copy = graph.post(_COPY_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _copy(client)

        assert copy.call_count == 1, "no_retry means one attempt, however Graph answers"


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            OnenoteSectionHandle("SECTION1").uri,
            OnenoteSectionGroupHandle("GROUP1").uri,
            _NOTEBOOK_ID,
            "https://onenote.example.invalid/notebook/1-SYNTHETICNOTEBOOK0000",
            "My notebook",
            "",
            "   ",
            "onenote:///notebooks/",
            "onenote:///notebooks/%20",
        ],
    )
    async def test_a_value_that_is_not_a_notebook_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError):
            _ = await _copy(client, notebook=value)

        assert len(graph.calls) == 0, "a refused handle copies nothing"

    async def test_the_refusal_names_the_tools_that_mint_a_notebook_handle(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="onenote_list_notebooks"):
            _ = await _copy(client, notebook="My notebook")
        with pytest.raises(ToolError, match="onenote_find_notebook_from_url"):
            _ = await _copy(client, notebook="My notebook")

    async def test_the_refusal_names_the_group_and_site_shapes(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await _copy(client, notebook="My notebook")

        message = str(refused.value)
        assert "onenote:///groups/{group}/" in message
        assert "onenote:///sites/{site}/" in message
        assert "This tool refuses a handle from a site notebook" in message


class TestWhatItAnswers:
    async def test_the_answer_is_the_operation_graph_started_from_the_body(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _copies_with_body(
            graph,
            payload=_operation_payload(operation_id="1-OPERATION0000!0-ABCDEF", status="Running"),
        )

        answer = await _copy(client)

        assert answer.status == "Running"
        assert "1-OPERATION0000" in answer.uri

    async def test_an_empty_202_with_only_the_operation_location_header_mints_the_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copy = _copies_with_header_only(graph, operation_id="1-HEADERONLY0000!0-ABCDEF")

        answer = await _copy(client)

        assert copy.call_count == 1
        assert "1-HEADERONLY0000" in answer.uri
        assert answer.status is None

    async def test_a_body_and_a_header_together_are_answered_from_the_body(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        body = _operation_payload(operation_id="1-FROMBODY0000!0-ABCDEF", status="Running")
        _ = graph.post(_COPY_PATH).mock(
            return_value=httpx.Response(
                202,
                json=body,
                headers={"Operation-Location": _operation_location("1-FROMHEADER0000!0-ABCDEF")},
            )
        )

        answer = await _copy(client)

        assert "1-FROMBODY0000" in answer.uri
        assert "1-FROMHEADER0000" not in answer.uri

    async def test_an_empty_202_with_neither_a_body_nor_a_header_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copy = graph.post(_COPY_PATH).mock(return_value=httpx.Response(202, content=b""))

        with pytest.raises(ToolError, match="named no operation"):
            _ = await _copy(client)

        assert copy.call_count == 1, "the copy was still sent before this tool gave up on it"

    async def test_a_body_with_no_id_and_no_header_is_the_same_refusal_as_an_empty_202(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _copies_with_body(graph, payload=_operation_payload(operation_id=None))

        with pytest.raises(ToolError, match="named no operation"):
            _ = await _copy(client)


class TestGraphFailures:
    async def test_a_404_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_COPY_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _copy(client)

    async def test_a_403_without_to_group_stays_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_COPY_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _copy(client)

    async def test_the_call_example_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        example = cast("Mapping[str, str]", copier.GRAPH_CALL_EXAMPLE)
        handle = onenote_notebook_handle(example["notebook"])
        assert handle is not None, "GRAPH_CALL_EXAMPLE's own notebook value is not a handle"
        route = graph.post(f"/me/onenote/notebooks/{handle.notebook_id}/copyNotebook").mock(
            return_value=httpx.Response(
                202,
                content=b"",
                headers={"Operation-Location": _operation_location(handle.notebook_id)},
            )
        )

        _ = await _copy(client, notebook=example["notebook"])

        assert route.call_count == 1

    def test_not_found_advice_points_at_the_finders(self) -> None:
        assert "onenote_list_notebooks" in copier.GRAPH_NOT_FOUND
        assert "onenote_find_notebook_from_url" in copier.GRAPH_NOT_FOUND

    def test_not_found_advice_names_to_group_as_a_cause(self) -> None:
        assert "`to_group`" in copier.GRAPH_NOT_FOUND
        assert "reach. Ask the user for the correct id." in copier.GRAPH_NOT_FOUND
        assert "teams_list_my_teams" not in copier.GRAPH_NOT_FOUND
        assert "the argument is not the problem" not in copier.GRAPH_NOT_FOUND

    async def test_a_403_with_to_group_is_advised_about_the_group(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph)
        _ = graph.post(_COPY_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(Advised) as refused:
            _ = await _copy(client, to_group=_GROUP_ID, confirm=_agrees)

        message = str(refused.value)
        assert message.startswith(
            "Microsoft 365 refused this request for the `to_group` that this call named."
        )
        assert "not a member of that group" in message
        assert "Notes.Create" in message
        assert (
            "If the user already has access, ask an administrator to examine the OneNote "
            + "permissions of this connector."
        ) in message
        assert "are not the problem" not in message
        assert "do not retry it" in message
        assert "(HTTP 403" in message
        assert isinstance(refused.value.__cause__, GraphForbidden)


def _group_source_copies(graph: respx.MockRouter) -> respx.Route:
    location = f"https://graph.microsoft.com/v1.0{_SOURCE_GROUP_ROOT}/operations/{_OPERATION_ID}"
    return graph.post(f"{_SOURCE_GROUP_ROOT}/notebooks/{_NOTEBOOK_ID}/copyNotebook").mock(
        return_value=httpx.Response(202, content=b"", headers={"Operation-Location": location})
    )


class TestCopyingIntoAMicrosoft365Group:
    async def test_to_group_asks_first_and_sends_the_group_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph, name="Work")
        copy = _copies_with_header_only(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _copy(client, to_group=_GROUP_ID, confirm=capturing)

        assert asked == [
            f"Copy the notebook 'Work' into the Microsoft 365 group with the id {_GROUP_ID!r}?"
        ]
        assert _sent(copy) == {"groupId": _GROUP_ID}

    async def test_to_group_and_a_new_name_reach_the_question_and_the_body(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph)
        copy = _copies_with_header_only(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _copy(client, to_group=_GROUP_ID, new_name="Team copy", confirm=capturing)

        assert "renamed 'Team copy'" in asked[0]
        sent = _sent(copy)
        assert sent == {"groupId": _GROUP_ID, "renameAs": "Team copy"}
        assert "siteId" not in sent
        assert "siteCollectionId" not in sent
        assert "notebookFolder" not in sent

    async def test_a_declined_copy_into_a_group_starts_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph)
        copy = _copies_with_header_only(graph)

        with pytest.raises(ToolError, match="Nothing was copied"):
            _ = await _copy(client, to_group=_GROUP_ID, confirm=_refuses)

        assert copy.call_count == 0

    async def test_about_binds_the_notebook_the_group_and_the_new_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph)
        _ = _copies_with_header_only(graph)
        bound: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert question
            bound.append(about)
            return None

        _ = await _copy(client, to_group=_GROUP_ID, confirm=capturing)
        _ = await _copy(client, to_group=_GROUP_ID, new_name="Team copy", confirm=capturing)

        assert bound == [
            write_state_for("copy_notebook", _NOTEBOOK_URI, _GROUP_ID, ""),
            write_state_for("copy_notebook", _NOTEBOOK_URI, _GROUP_ID, "Team copy"),
        ]

    async def test_a_group_source_is_copied_under_the_group_that_holds_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copy = _group_source_copies(graph)

        answer = await _copy(client, notebook=_GROUP_NOTEBOOK_URI)

        assert copy.call_count == 1
        assert len(graph.calls) == 1
        assert _sent(copy) == {}
        assert (
            answer.uri
            == OnenoteOperationHandle(
                _OPERATION_ID, owner=OnenoteOwner("groups", _SOURCE_GROUP_ID)
            ).uri
        )

    async def test_a_group_source_is_named_from_the_group_that_holds_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        name = _notebook_route(graph, path=f"{_SOURCE_GROUP_ROOT}/notebooks/{_NOTEBOOK_ID}")
        copy = _group_source_copies(graph)

        _ = await _copy(client, notebook=_GROUP_NOTEBOOK_URI, to_group=_GROUP_ID, confirm=_agrees)

        assert name.call_count == 1
        assert _sent(copy) == {"groupId": _GROUP_ID}

    async def test_the_first_round_asks_and_never_reaches_the_copy(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph, name="Work")
        copy = _copies_with_header_only(graph)

        answer = await copy_notebook(
            client,
            notebook=_NOTEBOOK_URI,
            to_group=_GROUP_ID,
            confirm=a_person_agrees(_modern_context()),
        )

        assert isinstance(answer, InputRequiredResult)
        assert answer.request_state == write_state_for(
            "copy_notebook", _NOTEBOOK_URI, _GROUP_ID, ""
        )
        requests = answer.input_requests or {}
        request = requests[next(iter(requests))]
        assert isinstance(request, ElicitRequest)
        assert isinstance(request.params, ElicitRequestFormParams)
        assert "Work" in request.params.message
        assert f"the Microsoft 365 group with the id {_GROUP_ID!r}" in request.params.message
        assert copy.call_count == 0

    async def test_the_second_round_copies_under_the_id_it_was_agreed_to_by(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph)
        copy = _copies_with_header_only(graph)

        first = await copy_notebook(
            client,
            notebook=_NOTEBOOK_URI,
            to_group=_GROUP_ID,
            confirm=a_person_agrees(_modern_context()),
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))

        answer = await copy_notebook(
            client,
            notebook=_NOTEBOOK_URI,
            to_group=_GROUP_ID,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": "copy"})},
                    state=first.request_state,
                )
            ),
            answer_pending=True,
        )

        assert isinstance(answer, OperationSummary)
        assert copy.call_count == 1
        assert _sent(copy) == {"groupId": _GROUP_ID}

    async def test_a_pending_decline_is_honored_even_without_to_group(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph)
        copy = _copies_with_header_only(graph)
        asked: list[str] = []

        async def refusing(question: str, about: str) -> str | None:
            assert about == write_state_for("copy_notebook", _NOTEBOOK_URI, "", "")
            asked.append(question)
            return "Nothing was copied."

        with pytest.raises(ToolError, match="Nothing was copied"):
            _ = await copy_notebook(
                client, notebook=_NOTEBOOK_URI, confirm=refusing, answer_pending=True
            )

        assert asked == ["Copy the notebook 'Work' into your own OneDrive?"]
        assert copy.call_count == 0

    async def test_register_asks_before_a_copy_into_a_group(
        self, transport: httpx.AsyncClient, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph)
        copy = _copies_with_header_only(graph)
        mcp: FastMCP = FastMCP(name="wiring-under-test")
        copier.register(mcp, transport)
        tool = await mcp.get_tool(copier.TOOL_NAME)
        assert isinstance(tool, FunctionTool)

        answer = cast(
            "OperationSummary | InputRequiredResult",
            await tool.fn(
                notebook=_NOTEBOOK_URI,
                new_name=None,
                to_group=_GROUP_ID,
                ctx=_modern_context(),
                client=client,
            ),
        )

        assert isinstance(answer, InputRequiredResult)
        assert copy.call_count == 0


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


class TestHowItDeclaresItself:
    def test_the_permission_is_notes_create(self) -> None:
        assert copier.GRAPH_PERMISSIONS == ("Notes.Create",)

    def test_the_call_example_is_a_notebook_handle(self) -> None:
        assert set(copier.GRAPH_CALL_EXAMPLE) == {"notebook"}

    async def test_the_call_example_is_accepted_by_the_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(copier.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_it_takes_three_arguments_and_no_others(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"notebook", "new_name", "to_group"}

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

    async def test_the_description_says_only_a_copy_into_a_group_is_asked_about(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = (tool.description or "").casefold()
        assert "asks the user to agree before it writes into a microsoft 365 group" in description
        assert "a copy into the user's own onedrive starts without a question" in description
        assert "do not call this tool again first" in description
        assert "onenote_get_operation" in description
        assert "the question names the group only by its id" in description
        assert "if you know the name of that group, tell it to the user before you call" in (
            description
        )

    async def test_the_timed_out_note_lists_the_notebooks_of_the_target_group(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert (
            "If this call named a `to_group`, pass that id to onenote_list_notebooks as `group`."
            in description
        )

    async def test_the_description_says_a_site_notebook_cannot_be_copied(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        assert "This tool cannot copy a notebook of a SharePoint site." in (tool.description or "")

    async def test_the_to_group_description_names_where_the_id_comes_from(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)
        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        to_group = cast("Mapping[str, object]", properties["to_group"])
        description = cast("str", to_group["description"])

        assert "A team id is a group id." in description
        assert "Ask the user for it, or copy a team id from an earlier result." in description
        assert "teams_list_my_teams" not in description
        assert "own OneDrive" in description

    async def test_the_notebook_description_names_the_group_shape(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)
        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        notebook = cast("Mapping[str, object]", properties["notebook"])
        description = cast("str", notebook["description"])

        assert "onenote:///groups/{group}/" in description
        assert (
            "This tool refuses a handle from a site notebook, which starts with "
            + "onenote:///sites/{site}/."
            in description
        )

    async def test_the_new_name_description_lists_the_forbidden_characters(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)
        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        new_name = cast("Mapping[str, object]", properties["new_name"])
        description = cast("str", new_name["description"])
        for character in "?*/:<>|'\"":
            assert character in description, f"{character!r} missing from the description"
        assert "400" not in description
        assert "409" not in description

    async def test_the_new_name_schema_sets_no_maximum_length(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)
        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        assert "maxLength" not in json.dumps(properties["new_name"])


class TestNotebooksOfASharePointSite:
    @pytest.mark.parametrize("to_group", [None, _GROUP_ID])
    async def test_a_site_source_is_refused_before_any_graph_call(
        self, client: GraphServiceClient, graph: respx.MockRouter, to_group: str | None
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await copy_notebook(
                client,
                notebook=_SITE_NOTEBOOK_URI,
                to_group=to_group,
                confirm=_never_asked,
                answer_pending=True,
            )

        assert len(graph.calls) == 0, "a copy from a site notebook reached Graph"
        message = str(refused.value)
        assert message.startswith("onenote_copy_notebook ")
        assert "notebook of a SharePoint site" in message
        assert "This same call fails again" in message
