import json
from collections.abc import Mapping
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
    OnenotePageHandle,
    OnenoteSectionGroupHandle,
    OnenoteSectionHandle,
)
from office_365_mcp.shared.notes import OperationSummary, write_state_for
from office_365_mcp.shared.seam import WRITE_ADDITIVE, Confirm
from office_365_mcp.tools import onenote_copy_section as copier
from office_365_mcp.tools.onenote_copy_section import a_person_agrees, copy_section

_SECTION_ID = "1-SYNTHETICSECTION0000!0-ABCDEF"
_NOTEBOOK_ID = "1-SYNTHETICNOTEBOOK0000!0-ABCDEF"
_GROUP_ID = "1-SYNTHETICGROUP0000!0-ABCDEF"
_OPERATION_ID = "1-SYNTHETICOPERATION0000!0-ABCDEF"

_SECTION_URI = OnenoteSectionHandle(_SECTION_ID).uri
_NOTEBOOK_URI = OnenoteNotebookHandle(_NOTEBOOK_ID).uri
_GROUP_URI = OnenoteSectionGroupHandle(_GROUP_ID).uri

_SECTION_GET_PATH = f"/me/onenote/sections/{_SECTION_ID}"
_COPY_TO_NOTEBOOK_PATH = f"/me/onenote/sections/{_SECTION_ID}/copyToNotebook"
_COPY_TO_GROUP_PATH = f"/me/onenote/sections/{_SECTION_ID}/copyToSectionGroup"
_NOTEBOOK_GET_PATH = f"/me/onenote/notebooks/{_NOTEBOOK_ID}"
_GROUP_GET_PATH = f"/me/onenote/sectionGroups/{_GROUP_ID}"


def _notebook_payload(
    *,
    notebook_id: str = _NOTEBOOK_ID,
    name: str | None = "Work",
    is_shared: bool | None = False,
    user_role: str | None = "Owner",
) -> dict[str, object]:
    return {"id": notebook_id, "displayName": name, "isShared": is_shared, "userRole": user_role}


def _group_payload(
    *,
    group_id: str = _GROUP_ID,
    display_name: str | None = "Archive",
    notebook: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": group_id,
        "displayName": display_name,
        "parentNotebook": dict(notebook) if notebook is not None else None,
    }


def _section_name_payload(
    *, section_id: str = _SECTION_ID, display_name: str | None = "Notes"
) -> dict[str, object]:
    return {"id": section_id, "displayName": display_name}


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


def _notebook_route(
    graph: respx.MockRouter,
    *,
    notebook_id: str = _NOTEBOOK_ID,
    is_shared: bool | None = False,
    user_role: str | None = "Owner",
    name: str | None = "Work",
) -> respx.Route:
    payload = _notebook_payload(
        notebook_id=notebook_id, name=name, is_shared=is_shared, user_role=user_role
    )
    return graph.get(f"/me/onenote/notebooks/{notebook_id}").mock(
        return_value=httpx.Response(200, json=payload)
    )


_GROUP_UNDER_NOTEBOOK: Mapping[str, object] = {"id": _NOTEBOOK_ID}


def _group_route(
    graph: respx.MockRouter,
    *,
    group_id: str = _GROUP_ID,
    display_name: str | None = "Archive",
    notebook: Mapping[str, object] | None = _GROUP_UNDER_NOTEBOOK,
) -> respx.Route:
    return graph.get(f"/me/onenote/sectionGroups/{group_id}").mock(
        return_value=httpx.Response(
            200,
            json=_group_payload(group_id=group_id, display_name=display_name, notebook=notebook),
        )
    )


def _section_name_route(
    graph: respx.MockRouter, *, display_name: str | None = "Notes"
) -> respx.Route:
    return graph.get(_SECTION_GET_PATH).mock(
        return_value=httpx.Response(200, json=_section_name_payload(display_name=display_name))
    )


def _operation_location(operation_id: str = _OPERATION_ID) -> str:
    return f"https://graph.microsoft.com/v1.0/me/onenote/operations/{operation_id}"


def _copies_to_notebook_with_body(
    graph: respx.MockRouter, *, status: int = 202, payload: Mapping[str, object] | None = None
) -> respx.Route:
    body = dict(payload) if payload is not None else _operation_payload()
    return graph.post(_COPY_TO_NOTEBOOK_PATH).mock(return_value=httpx.Response(status, json=body))


def _copies_to_notebook_with_header_only(
    graph: respx.MockRouter, *, status: int = 202, operation_id: str = _OPERATION_ID
) -> respx.Route:
    return graph.post(_COPY_TO_NOTEBOOK_PATH).mock(
        return_value=httpx.Response(
            status, content=b"", headers={"Operation-Location": _operation_location(operation_id)}
        )
    )


def _copies_to_group_with_body(
    graph: respx.MockRouter, *, status: int = 202, payload: Mapping[str, object] | None = None
) -> respx.Route:
    body = dict(payload) if payload is not None else _operation_payload()
    return graph.post(_COPY_TO_GROUP_PATH).mock(return_value=httpx.Response(status, json=body))


def _copies_to_group_with_header_only(
    graph: respx.MockRouter, *, status: int = 202, operation_id: str = _OPERATION_ID
) -> respx.Route:
    return graph.post(_COPY_TO_GROUP_PATH).mock(
        return_value=httpx.Response(
            status, content=b"", headers={"Operation-Location": _operation_location(operation_id)}
        )
    )


def _private_notebook(graph: respx.MockRouter) -> None:
    _ = _notebook_route(graph, is_shared=False, user_role="Owner")


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
    section: str = _SECTION_URI,
    to_notebook: str | None = _NOTEBOOK_URI,
    to_section_group: str | None = None,
    new_name: str | None = None,
    confirm: Confirm = _agrees,
) -> OperationSummary:
    answer = await copy_section(
        client,
        section=section,
        to_notebook=to_notebook,
        to_section_group=to_section_group,
        new_name=new_name,
        confirm=confirm,
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


class TestWhatItSendsToGraphForANotebookDestination:
    async def test_a_private_notebook_reads_the_notebook_then_copies_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private_notebook(graph)
        copy = _copies_to_notebook_with_header_only(graph)

        _ = await _copy(client)

        assert copy.call_count == 1
        assert len(graph.calls) == 2, "the notebook read and the copy"

    async def test_a_shared_notebook_also_reads_the_source_section_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        _ = _section_name_route(graph)
        copy = _copies_to_notebook_with_header_only(graph)

        _ = await _copy(client)

        assert copy.call_count == 1
        assert len(graph.calls) == 3, "the notebook read, the source section read, the copy"

    async def test_the_copy_is_sent_with_only_the_destination_id_when_no_rename_is_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private_notebook(graph)
        copy = _copies_to_notebook_with_header_only(graph)

        _ = await _copy(client)

        assert _sent(copy) == {"id": _NOTEBOOK_ID}

    async def test_a_new_name_is_sent_as_rename_as(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private_notebook(graph)
        copy = _copies_to_notebook_with_header_only(graph)

        _ = await _copy(client, new_name="Renamed section")

        assert _sent(copy) == {"id": _NOTEBOOK_ID, "renameAs": "Renamed section"}

    async def test_no_group_or_site_keys_are_ever_sent(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private_notebook(graph)
        copy = _copies_to_notebook_with_header_only(graph)

        _ = await _copy(client, new_name="Renamed section")

        sent = _sent(copy)
        assert "groupId" not in sent
        assert "siteId" not in sent
        assert "siteCollectionId" not in sent

    async def test_the_section_name_get_is_not_issued_when_the_notebook_is_private(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        section_route = _section_name_route(graph)
        _private_notebook(graph)
        _ = _copies_to_notebook_with_header_only(graph)

        _ = await _copy(client)

        assert section_route.call_count == 0, "nobody was asked, so the name was never needed"

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_copy_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private_notebook(graph)
        copy = graph.post(_COPY_TO_NOTEBOOK_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _copy(client)

        assert copy.call_count == 1, "no_retry means one attempt, however Graph answers"


class TestWhatItSendsToGraphForASectionGroupDestination:
    async def test_it_reads_the_group_then_the_notebook_then_copies(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _group_route(graph, notebook={"id": _NOTEBOOK_ID})
        _ = _notebook_route(graph, is_shared=False, user_role="Owner")
        copy = _copies_to_group_with_header_only(graph)

        _ = await _copy(client, to_notebook=None, to_section_group=_GROUP_URI)

        assert copy.call_count == 1
        assert len(graph.calls) == 3, "the group read, the notebook read and the copy"

    async def test_the_copy_body_names_the_group_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _group_route(graph, notebook={"id": _NOTEBOOK_ID})
        _ = _notebook_route(graph, is_shared=False, user_role="Owner")
        copy = _copies_to_group_with_header_only(graph)

        _ = await _copy(client, to_notebook=None, to_section_group=_GROUP_URI)

        assert _sent(copy) == {"id": _GROUP_ID}

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_copy_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _group_route(graph, notebook={"id": _NOTEBOOK_ID})
        _ = _notebook_route(graph, is_shared=False, user_role="Owner")
        copy = graph.post(_COPY_TO_GROUP_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _copy(client, to_notebook=None, to_section_group=_GROUP_URI)

        assert copy.call_count == 1, "no_retry means one attempt, however Graph answers"


class TestWhatItRefuses:
    async def test_neither_destination_is_refused_before_reaching_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="exactly one destination"):
            _ = await _copy(client, to_notebook=None, to_section_group=None)

        assert len(graph.calls) == 0

    async def test_both_destinations_is_refused_before_reaching_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="exactly one destination"):
            _ = await _copy(client, to_notebook=_NOTEBOOK_URI, to_section_group=_GROUP_URI)

        assert len(graph.calls) == 0

    @pytest.mark.parametrize(
        "value",
        [
            OnenoteNotebookHandle(_NOTEBOOK_ID).uri,
            OnenotePageHandle("PAGE1").uri,
            _SECTION_ID,
            "",
            "   ",
            "onenote:///sections/",
        ],
    )
    async def test_a_value_that_is_not_a_section_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError):
            _ = await _copy(client, section=value)

        assert len(graph.calls) == 0

    async def test_the_section_refusal_names_the_tools_that_mint_a_section_handle(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="onenote_list_sections"):
            _ = await _copy(client, section="a section, not a handle")

    @pytest.mark.parametrize(
        "value",
        [OnenoteSectionHandle(_SECTION_ID).uri, _NOTEBOOK_ID, "", "   "],
    )
    async def test_a_value_that_is_not_a_notebook_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError):
            _ = await _copy(client, to_notebook=value, to_section_group=None)

        assert len(graph.calls) == 0

    async def test_the_notebook_refusal_names_onenote_create_notebook(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="onenote_create_notebook"):
            _ = await _copy(client, to_notebook="not a handle", to_section_group=None)

    @pytest.mark.parametrize(
        "value",
        [OnenoteSectionHandle(_SECTION_ID).uri, _GROUP_ID, "", "   "],
    )
    async def test_a_value_that_is_not_a_section_group_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError):
            _ = await _copy(client, to_notebook=None, to_section_group=value)

        assert len(graph.calls) == 0

    async def test_the_section_group_refusal_names_onenote_create_section_group(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="onenote_create_section_group"):
            _ = await _copy(client, to_notebook=None, to_section_group="not a handle")

    async def test_the_section_handle_is_checked_before_the_destination(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="section handle"):
            _ = await _copy(client, section="not a handle", to_notebook="also not a handle")

        assert len(graph.calls) == 0

    async def test_the_no_destination_refusal_says_a_correction_would_succeed(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="corrected call succeeds"):
            _ = await _copy(client, to_notebook=None, to_section_group=None)

    async def test_the_notebook_refusal_says_a_correction_would_succeed(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="corrected call succeeds"):
            _ = await _copy(client, to_notebook="not a handle", to_section_group=None)

    async def test_the_section_group_refusal_says_a_correction_would_succeed(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="corrected call succeeds"):
            _ = await _copy(client, to_notebook=None, to_section_group="not a handle")


class TestWhatItAnswers:
    async def test_the_answer_is_the_operation_graph_started_from_the_body(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private_notebook(graph)
        _ = _copies_to_notebook_with_body(
            graph,
            payload=_operation_payload(operation_id="1-OPERATION0000!0-ABCDEF", status="Running"),
        )

        answer = await _copy(client)

        assert answer.status == "Running"
        assert "1-OPERATION0000" in answer.uri

    async def test_an_empty_202_with_only_the_operation_location_header_mints_the_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private_notebook(graph)
        copy = _copies_to_notebook_with_header_only(graph, operation_id="1-HEADERONLY0000!0-ABCDEF")

        answer = await _copy(client)

        assert copy.call_count == 1
        assert "1-HEADERONLY0000" in answer.uri
        assert answer.status is None

    async def test_a_body_and_a_header_together_are_answered_from_the_body(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private_notebook(graph)
        body = _operation_payload(operation_id="1-FROMBODY0000!0-ABCDEF", status="Running")
        _ = graph.post(_COPY_TO_NOTEBOOK_PATH).mock(
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
        _private_notebook(graph)
        copy = graph.post(_COPY_TO_NOTEBOOK_PATH).mock(
            return_value=httpx.Response(202, content=b"")
        )

        with pytest.raises(ToolError, match="named no operation"):
            _ = await _copy(client)

        assert copy.call_count == 1, "the copy was still sent before this tool gave up on it"

    async def test_a_body_with_no_id_and_no_header_is_the_same_refusal_as_an_empty_202(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private_notebook(graph)
        _ = _copies_to_notebook_with_body(graph, payload=_operation_payload(operation_id=None))

        with pytest.raises(ToolError, match="named no operation"):
            _ = await _copy(client)


class TestGraphFailures:
    async def test_a_404_on_the_copy_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private_notebook(graph)
        _ = graph.post(_COPY_TO_NOTEBOOK_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _copy(client)

    async def test_a_404_on_the_notebook_read_is_a_not_found_and_nothing_is_copied(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_NOTEBOOK_GET_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )
        copy = _copies_to_notebook_with_header_only(graph)

        with pytest.raises(GraphNotFound):
            _ = await _copy(client)

        assert copy.call_count == 0

    async def test_a_403_on_the_copy_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private_notebook(graph)
        _ = graph.post(_COPY_TO_NOTEBOOK_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _copy(client)

    def test_not_found_advice_points_at_the_listers(self) -> None:
        assert "onenote_list_sections" in copier.GRAPH_NOT_FOUND
        assert "onenote_list_notebooks" in copier.GRAPH_NOT_FOUND


class TestThePersonBetweenTheCopyAndTheOthersInTheNotebook:
    async def test_the_users_own_unshared_notebook_is_copied_into_without_a_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _private_notebook(graph)
        copy = _copies_to_notebook_with_header_only(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _copy(client, confirm=counting)

        assert asked == [], "the user's own private notebook was put to a person anyway"
        assert copy.call_count == 1

    async def test_a_shared_notebook_is_asked_about_and_a_refusal_copies_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        _ = _section_name_route(graph)
        copy = _copies_to_notebook_with_header_only(graph)

        with pytest.raises(ToolError, match="Nothing was copied"):
            _ = await _copy(client, confirm=_refuses)

        assert copy.call_count == 0

    async def test_a_notebook_the_user_does_not_own_is_asked_about(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph, is_shared=False, user_role="Contributor")
        _ = _section_name_route(graph)
        copy = _copies_to_notebook_with_header_only(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _copy(client, confirm=counting)

        assert len(asked) == 1
        assert copy.call_count == 1

    async def test_a_private_section_group_destination_is_not_asked_about(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _group_route(graph, notebook={"id": _NOTEBOOK_ID})
        _ = _notebook_route(graph, is_shared=False, user_role="Owner")
        copy = _copies_to_group_with_header_only(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _copy(client, to_notebook=None, to_section_group=_GROUP_URI, confirm=counting)

        assert asked == []
        assert copy.call_count == 1

    async def test_a_shared_section_group_destination_is_asked_about(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _group_route(graph, display_name="Archive", notebook={"id": _NOTEBOOK_ID})
        _ = _notebook_route(graph, is_shared=True, user_role="Owner", name="Work")
        _ = _section_name_route(graph)
        copy = _copies_to_group_with_header_only(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _copy(client, to_notebook=None, to_section_group=_GROUP_URI, confirm=counting)

        assert len(asked) == 1
        assert "the section group 'Archive' of the notebook 'Work'" in asked[0]
        assert copy.call_count == 1

    async def test_the_question_names_the_section_the_notebook_and_the_reason(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph, is_shared=True, user_role="Owner", name="Work")
        _ = _section_name_route(graph, display_name="Notes")
        _ = _copies_to_notebook_with_header_only(graph)
        asked: list[str] = []
        bound: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            asked.append(question)
            bound.append(about)
            return None

        _ = await _copy(client, confirm=capturing)

        assert len(asked) == 1
        question = asked[0]
        assert "Notes" in question
        assert "Work" in question
        assert "shared with other people" in question
        assert bound == [write_state_for("copy_section", _SECTION_ID, _NOTEBOOK_URI, "")]

    async def test_the_question_mentions_the_new_name_when_one_is_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        _ = _section_name_route(graph)
        _ = _copies_to_notebook_with_header_only(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _copy(client, new_name="Renamed section", confirm=capturing)

        assert "Renamed section" in asked[0]

    async def test_the_question_names_nothing_none_of_it_has(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph, is_shared=True, user_role="Owner", name=None)
        _ = _section_name_route(graph, display_name=None)
        _ = _copies_to_notebook_with_header_only(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _copy(client, confirm=capturing)

        assert "an unnamed section" in asked[0]
        assert "an unnamed notebook" in asked[0]

    async def test_about_changes_with_the_destination_and_the_new_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        _ = _section_name_route(graph)
        _ = _copies_to_notebook_with_header_only(graph)
        bound: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert question
            bound.append(about)
            return None

        _ = await _copy(client, confirm=capturing)
        _ = await _copy(client, confirm=capturing)
        _ = await _copy(client, new_name="Renamed", confirm=capturing)

        assert bound[0] == bound[1]
        assert bound[2] != bound[0]

    async def test_about_differs_between_a_notebook_and_a_section_group_of_the_same_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph, notebook_id=_GROUP_ID, is_shared=True, user_role="Owner")
        _ = _group_route(graph, group_id=_GROUP_ID, notebook={"id": _NOTEBOOK_ID})
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        _ = _section_name_route(graph)
        _ = graph.post(_COPY_TO_NOTEBOOK_PATH).mock(
            return_value=httpx.Response(
                202, content=b"", headers={"Operation-Location": _operation_location()}
            )
        )
        _ = graph.post(_COPY_TO_GROUP_PATH).mock(
            return_value=httpx.Response(
                202, content=b"", headers={"Operation-Location": _operation_location()}
            )
        )
        bound: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert question
            bound.append(about)
            return None

        _ = await _copy(client, to_notebook=OnenoteNotebookHandle(_GROUP_ID).uri, confirm=capturing)
        _ = await _copy(client, to_notebook=None, to_section_group=_GROUP_URI, confirm=capturing)

        assert bound[0] != bound[1]

    @pytest.mark.parametrize(
        "answer",
        [
            DeclinedElicitation(),
            CancelledElicitation(),
            AcceptedElicitation(data="do not copy"),
            RuntimeError("elicitation not supported"),
            ToolError("the client refused the request"),
        ],
        ids=["declined", "cancelled", "another-answer", "cannot-ask", "client-error"],
    )
    async def test_no_refusal_is_ever_raised(self, answer: object) -> None:
        confirm = a_person_agrees(_context(answer))

        refusal = await confirm("Copy this section?", "synthetic-state")

        assert isinstance(refusal, str)
        assert refusal

    async def test_a_refusal_this_tool_words_opens_by_saying_nothing_was_copied(self) -> None:
        confirm = a_person_agrees(_context(DeclinedElicitation()))

        refusal = await confirm("Copy this section?", "synthetic-state")

        assert isinstance(refusal, str)
        assert refusal.startswith("Nothing was copied.")

    async def test_agreeing_answers_with_no_refusal(self) -> None:
        confirm = a_person_agrees(_context(AcceptedElicitation(data="copy")))

        assert await confirm("Copy this section?", "synthetic-state") is None


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
    async def test_the_first_round_asks_and_never_reaches_the_copy(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        _ = _section_name_route(graph)
        copy = _copies_to_notebook_with_header_only(graph)

        answer = await copy_section(
            client,
            section=_SECTION_URI,
            to_notebook=_NOTEBOOK_URI,
            confirm=a_person_agrees(_modern_context()),
        )

        assert isinstance(answer, InputRequiredResult)
        assert answer.request_state == write_state_for(
            "copy_section", _SECTION_ID, _NOTEBOOK_URI, ""
        )
        assert copy.call_count == 0

    async def test_the_first_round_asks_the_question_this_tool_words(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph, is_shared=True, user_role="Owner", name="Work")
        _ = _section_name_route(graph)
        _ = _copies_to_notebook_with_header_only(graph)

        answer = await copy_section(
            client,
            section=_SECTION_URI,
            to_notebook=_NOTEBOOK_URI,
            confirm=a_person_agrees(_modern_context()),
        )

        assert isinstance(answer, InputRequiredResult)
        requests = answer.input_requests or {}
        request = requests[next(iter(requests))]
        assert isinstance(request, ElicitRequest)
        params = request.params
        assert isinstance(params, ElicitRequestFormParams)
        assert "Work" in params.message

    async def test_the_second_round_copies_under_the_id_it_was_agreed_to_by(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        _ = _section_name_route(graph)
        copy = _copies_to_notebook_with_header_only(graph)
        state = write_state_for("copy_section", _SECTION_ID, _NOTEBOOK_URI, "")

        first = await copy_section(
            client,
            section=_SECTION_URI,
            to_notebook=_NOTEBOOK_URI,
            confirm=a_person_agrees(_modern_context()),
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))

        answer = await copy_section(
            client,
            section=_SECTION_URI,
            to_notebook=_NOTEBOOK_URI,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": "copy"})},
                    state=state,
                )
            ),
        )

        assert isinstance(answer, OperationSummary)
        assert copy.call_count == 1

    async def test_an_answer_bound_to_another_request_copies_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        _ = _section_name_route(graph)
        copy = _copies_to_notebook_with_header_only(graph)

        first = await copy_section(
            client,
            section=_SECTION_URI,
            to_notebook=_NOTEBOOK_URI,
            confirm=a_person_agrees(_modern_context()),
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await copy_section(
                client,
                section=_SECTION_URI,
                to_notebook=_NOTEBOOK_URI,
                confirm=a_person_agrees(
                    _modern_context(
                        answers={key: ElicitResult(action="accept", content={"value": "copy"})},
                        state="synthetic-other-state",
                    )
                ),
            )

        assert copy.call_count == 0

    async def test_a_pending_decline_is_honored_even_when_the_fresh_read_says_private(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        notebook_route = graph.get(_NOTEBOOK_GET_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_notebook_payload(is_shared=True, user_role="Owner")),
                httpx.Response(200, json=_notebook_payload(is_shared=False, user_role="Owner")),
            ]
        )
        section_route = _section_name_route(graph)
        copy = _copies_to_notebook_with_header_only(graph)

        first = await copy_section(
            client,
            section=_SECTION_URI,
            to_notebook=_NOTEBOOK_URI,
            confirm=a_person_agrees(_modern_context()),
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))
        state = first.request_state
        assert state is not None

        with pytest.raises(ToolError, match="Nothing was copied"):
            _ = await copy_section(
                client,
                section=_SECTION_URI,
                to_notebook=_NOTEBOOK_URI,
                confirm=a_person_agrees(
                    _modern_context(answers={key: ElicitResult(action="decline")}, state=state)
                ),
                answer_pending=True,
            )

        assert copy.call_count == 0
        assert notebook_route.call_count == 2
        assert section_route.call_count == 2, (
            "the source name is read again each round the question is asked in"
        )

    async def test_a_pending_accept_still_copies_when_the_fresh_read_says_private(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        notebook_route = graph.get(_NOTEBOOK_GET_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_notebook_payload(is_shared=True, user_role="Owner")),
                httpx.Response(200, json=_notebook_payload(is_shared=False, user_role="Owner")),
            ]
        )
        section_route = _section_name_route(graph)
        copy = _copies_to_notebook_with_header_only(graph)

        first = await copy_section(
            client,
            section=_SECTION_URI,
            to_notebook=_NOTEBOOK_URI,
            confirm=a_person_agrees(_modern_context()),
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))
        state = first.request_state
        assert state is not None

        answer = await copy_section(
            client,
            section=_SECTION_URI,
            to_notebook=_NOTEBOOK_URI,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": "copy"})},
                    state=state,
                )
            ),
            answer_pending=True,
        )

        assert isinstance(answer, OperationSummary)
        assert copy.call_count == 1
        assert notebook_route.call_count == 2
        assert section_route.call_count == 2


class TestTheClientThatCannotAsk:
    async def test_a_client_that_cannot_ask_copies_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        _ = _section_name_route(graph)
        copy = _copies_to_notebook_with_header_only(graph)

        class _CannotAsk:
            request_context: object = None

            async def elicit(self, message: str, response_type: object = None) -> object:
                assert message and response_type is not None
                raise RuntimeError("elicitation not supported")

        confirm = a_person_agrees(cast("Context", cast("object", _CannotAsk())))

        with pytest.raises(ToolError, match="does not support elicitation"):
            _ = await copy_section(
                client, section=_SECTION_URI, to_notebook=_NOTEBOOK_URI, confirm=confirm
            )

        assert copy.call_count == 0


class TestHowRegisterWiresThePendingAnswer:
    async def test_register_consults_a_pending_answer_the_fresh_read_alone_would_skip(
        self, transport: httpx.AsyncClient, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        notebook_route = graph.get(_NOTEBOOK_GET_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_notebook_payload(is_shared=True, user_role="Owner")),
                httpx.Response(200, json=_notebook_payload(is_shared=False, user_role="Owner")),
            ]
        )
        _ = _section_name_route(graph)
        copy = _copies_to_notebook_with_header_only(graph)
        mcp: FastMCP = FastMCP(name="wiring-under-test")
        copier.register(mcp, transport)
        tool = await mcp.get_tool(copier.TOOL_NAME)
        assert tool is not None, "register left the tool off the server"
        assert isinstance(tool, FunctionTool)

        first = cast(
            "OperationSummary | InputRequiredResult",
            await tool.fn(
                section=_SECTION_URI,
                to_notebook=_NOTEBOOK_URI,
                to_section_group=None,
                new_name=None,
                ctx=_modern_context(),
                client=client,
            ),
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))
        state = first.request_state
        assert state is not None

        with pytest.raises(ToolError, match="Nothing was copied"):
            _ = cast(
                "OperationSummary | InputRequiredResult",
                await tool.fn(
                    section=_SECTION_URI,
                    to_notebook=_NOTEBOOK_URI,
                    to_section_group=None,
                    new_name=None,
                    ctx=_modern_context(answers={key: ElicitResult(action="decline")}, state=state),
                    client=client,
                ),
            )

        assert copy.call_count == 0
        assert notebook_route.call_count == 2


class TestHowItDeclaresItself:
    def test_the_permission_is_notes_create(self) -> None:
        assert copier.GRAPH_PERMISSIONS == ("Notes.Create",)

    def test_the_call_example_is_a_section_and_a_notebook_handle(self) -> None:
        assert set(copier.GRAPH_CALL_EXAMPLE) == {"section", "to_notebook"}

    async def test_the_call_example_is_accepted_by_the_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(copier.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_it_takes_four_arguments_and_no_others(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"section", "to_notebook", "to_section_group", "new_name"}

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

    async def test_the_description_says_exactly_one_destination_and_not_safe_to_retry(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = (tool.description or "").casefold()
        assert "exactly one" in description
        assert "not safe to retry blindly" in description
        assert "onenote_get_operation" in description

    async def test_the_to_notebook_description_names_onenote_create_notebook(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)
        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        to_notebook = cast("Mapping[str, object]", properties["to_notebook"])
        assert "onenote_create_notebook" in cast("str", to_notebook["description"])

    async def test_the_to_section_group_description_names_onenote_create_section_group(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)
        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        to_section_group = cast("Mapping[str, object]", properties["to_section_group"])
        assert "onenote_create_section_group" in cast("str", to_section_group["description"])
