import json
from collections.abc import Mapping, Sequence
from typing import Literal, cast

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
from pydantic import ValidationError
from respx.models import Call

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound, GraphUnavailable
from office_365_mcp.shared.handles import (
    OnenotePageHandle,
    OnenoteSectionHandle,
    onenote_page_handle,
)
from office_365_mcp.shared.notes import PageSummary, write_state_for
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE, Confirm
from office_365_mcp.tools import onenote_edit_page as editor
from office_365_mcp.tools.onenote_edit_page import EditCommand, a_person_agrees, edit_page

_PAGE_ID = "1-SYNTHETICPAGE00000000000000000000!0-ABCDEF"

_PAGE_URI = OnenotePageHandle(_PAGE_ID).uri

_PATCH_PATH = f"/me/onenote/pages/{_PAGE_ID}/onenotePatchContent"

_GET_PATH = f"/me/onenote/pages/{_PAGE_ID}"

_NOTEBOOK_ID = "NOTEBOOK1"

_NOTEBOOK_GET_PATH = f"/me/onenote/notebooks/{_NOTEBOOK_ID}"

_APPEND_COMMAND = EditCommand(target="body", action="append", content="<p>Appended.</p>")
_REPLACE_COMMAND = EditCommand(
    target="div:{33f8a2}{1}", action="replace", content="<p>Replaced.</p>"
)
_DELETE_COMMAND = EditCommand(target="#intro", action="delete")


def _page_payload(
    *,
    page_id: str | None = _PAGE_ID,
    title: str | None = "Meeting notes",
    created: str | None = "2026-01-01T00:00:00Z",
    last_modified: str | None = "2026-01-05T12:30:00Z",
    web_url: str | None = "https://onenote.example.invalid/web",
    client_url: str | None = "https://onenote.example.invalid/client",
    section: Mapping[str, object] | None = None,
    notebook: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": page_id,
        "title": title,
        "createdDateTime": created,
        "lastModifiedDateTime": last_modified,
        "links": {
            "oneNoteWebUrl": {"href": web_url} if web_url is not None else None,
            "oneNoteClientUrl": {"href": client_url} if client_url is not None else None,
        },
        "parentSection": dict(section) if section is not None else None,
        "parentNotebook": dict(notebook) if notebook is not None else None,
    }


_SECTION = {"id": "SECTION1", "displayName": "General"}
_NOTEBOOK = {"id": _NOTEBOOK_ID, "displayName": "Work"}


def _notebook_payload(
    *,
    notebook_id: str = _NOTEBOOK_ID,
    name: str | None = "Work",
    is_shared: bool | None = False,
    user_role: str | None = "Owner",
) -> dict[str, object]:
    return {"id": notebook_id, "displayName": name, "isShared": is_shared, "userRole": user_role}


def _patches(graph: respx.MockRouter, *, status: int = 204) -> respx.Route:
    return graph.post(_PATCH_PATH).mock(return_value=httpx.Response(status))


def _rereads(graph: respx.MockRouter, payload: Mapping[str, object]) -> respx.Route:
    return graph.get(_GET_PATH).mock(return_value=httpx.Response(200, json=dict(payload)))


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


async def _agrees(question: str, about: str) -> str | None:
    assert question, "the person was asked nothing at all"
    assert about, "the answer was bound to nothing"
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return "Nothing was changed."


async def _edit(
    client: GraphServiceClient,
    *,
    page: str = _PAGE_URI,
    commands: list[EditCommand] | None = None,
    confirm: Confirm = _agrees,
) -> PageSummary:
    answer = await edit_page(
        client, page=page, commands=commands or [_APPEND_COMMAND], confirm=confirm
    )
    assert isinstance(answer, PageSummary), "this call was answered with a question, not a page"
    return answer


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


def _made(route: respx.Route) -> Sequence[Call]:
    return cast("Sequence[Call]", route.calls)


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    editor.register(mcp, transport)
    tool = await mcp.get_tool(editor.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestTheCommandValidator:
    def test_delete_with_content_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="delete command takes no content"):
            _ = EditCommand(target="#p1", action="delete", content="<p>x</p>")

    def test_delete_without_content_is_accepted(self) -> None:
        command = EditCommand(target="#p1", action="delete")
        assert command.content is None

    @pytest.mark.parametrize("action", ["append", "insert", "prepend", "replace"])
    def test_every_other_action_without_content_is_refused(
        self, action: Literal["append", "insert", "prepend", "replace"]
    ) -> None:
        with pytest.raises(ValidationError, match="needs content"):
            _ = EditCommand(target="#p1", action=action)

    @pytest.mark.parametrize("action", ["append", "insert", "prepend", "replace"])
    def test_every_other_action_with_content_is_accepted(
        self, action: Literal["append", "insert", "prepend", "replace"]
    ) -> None:
        command = EditCommand(target="#p1", action=action, content="<p>x</p>")
        assert command.content == "<p>x</p>"


class TestWhatItSendsToGraph:
    async def test_it_patches_the_content_then_rereads_the_page_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _patches(graph)
        page_route = _rereads(graph, _page_payload())

        _ = await _edit(client)

        assert patch.call_count == 1
        assert page_route.call_count == 2, "the audience pre-read and the post-write re-read"
        assert len(graph.calls) == 3, "an edit costs the pre-read, the patch and the re-read"

    async def test_the_pre_read_happens_before_the_patch_and_the_reread_after(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _patches(graph)
        _ = _rereads(graph, _page_payload())

        _ = await _edit(client)

        made = cast("Sequence[Call]", graph.calls)
        assert [call.request.method for call in made] == ["GET", "POST", "GET"]
        assert made[0].request.url.path.endswith(_GET_PATH)
        assert made[1].request.url.path.endswith(_PATCH_PATH)
        assert made[2].request.url.path.endswith(_GET_PATH)

    async def test_the_patch_maps_every_action_and_position_to_the_graph_enum_spelling(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _patches(graph)
        _ = _rereads(graph, _page_payload())
        commands = [
            EditCommand(target="#p1", action="insert", position="before", content="<p>x</p>"),
            EditCommand(target="#p2", action="delete"),
        ]

        _ = await _edit(client, commands=commands)

        assert _sent(patch) == {
            "commands": [
                {"action": "Insert", "content": "<p>x</p>", "position": "Before", "target": "#p1"},
                {"action": "Delete", "target": "#p2"},
            ]
        }

    async def test_a_command_with_no_position_carries_no_position_key_on_the_wire(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _patches(graph)
        _ = _rereads(graph, _page_payload())

        _ = await _edit(client, commands=[_APPEND_COMMAND])

        sent = _sent(patch)
        commands = cast("list[dict[str, object]]", sent["commands"])
        assert set(commands[0]) == {"action", "content", "target"}

    async def test_every_action_spelling_reaches_graph_capitalized(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _patches(graph)
        _ = _rereads(graph, _page_payload())
        commands = [
            EditCommand(target="body", action="append", content="<p>a</p>"),
            EditCommand(target="#p1", action="insert", content="<p>b</p>"),
            EditCommand(target="ol:{1}", action="prepend", content="<li>c</li>"),
            EditCommand(target="div:{2}", action="replace", content="<p>d</p>"),
            EditCommand(target="#p3", action="delete"),
        ]

        _ = await _edit(client, commands=commands)

        sent_commands = cast("list[dict[str, object]]", _sent(patch)["commands"])
        assert [command["action"] for command in sent_commands] == [
            "Append",
            "Insert",
            "Prepend",
            "Replace",
            "Delete",
        ]

    async def test_the_patch_content_type_is_json(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _patches(graph)
        _ = _rereads(graph, _page_payload())

        _ = await _edit(client)

        assert patch.calls.last.request.headers["content-type"] == "application/json"

    async def test_the_reread_asks_for_the_same_fields_a_page_listing_would(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _patches(graph)
        reread = _rereads(graph, _page_payload())

        _ = await _edit(client)

        query = reread.calls.last.request.url.params
        assert query["$select"] == "id,title,createdDateTime,lastModifiedDateTime,links"
        assert query["$expand"] == "parentSection,parentNotebook"

    async def test_the_pre_read_asks_only_for_id_title_and_the_parent_notebook(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        page_route = _rereads(graph, _page_payload())
        _ = _patches(graph)

        _ = await _edit(client)

        query = _made(page_route)[0].request.url.params
        assert query["$select"] == "id,title"
        assert query["$expand"] == "parentNotebook"

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_patch_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = graph.post(_PATCH_PATH).mock(return_value=httpx.Response(503))
        reread = graph.get(_GET_PATH).mock(return_value=httpx.Response(200, json=_page_payload()))

        with pytest.raises(GraphUnavailable):
            _ = await _edit(client)

        assert patch.call_count == 1, "no_retry means one attempt, however Graph answers"
        assert reread.call_count == 1, "only the pre-read happened; a failed write is never reread"


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            OnenoteSectionHandle("SECTION1").uri,
            "1-SYNTHETICPAGE00000000000000000000!0-ABCDEF",
            "https://onenote.example.invalid/page/1-SYNTHETICPAGE",
            "Meeting notes",
            "",
            "   ",
            "onenote:///pages/",
            "onenote:///pages/%20",
        ],
    )
    async def test_a_value_that_is_not_a_page_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError):
            _ = await _edit(client, page=value)

        assert len(graph.calls) == 0, "a refused handle changes nothing"

    async def test_the_refusal_names_the_tool_that_mints_a_page_handle(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="onenote_list_pages"):
            _ = await _edit(client, page="Meeting notes")

    async def test_a_section_handle_is_refused_by_name(self, client: GraphServiceClient) -> None:
        with pytest.raises(ToolError, match="section handle"):
            _ = await _edit(client, page=OnenoteSectionHandle("SECTION1").uri)


class TestWhatItAnswers:
    async def test_the_answer_is_the_page_as_graph_holds_it_after_the_write(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _patches(graph)
        _ = _rereads(
            graph,
            _page_payload(
                title="Updated title",
                last_modified="2026-01-09T08:00:00Z",
                section=_SECTION,
                notebook=_NOTEBOOK,
            ),
        )
        _ = _notebook_route(graph)

        answer = await _edit(client)

        assert answer.uri == _PAGE_URI
        assert answer.title == "Updated title"
        assert answer.section_name == "General"
        assert answer.notebook_name == "Work"
        assert answer.section_uri == OnenoteSectionHandle("SECTION1").uri

    async def test_the_answer_is_read_off_graph_and_never_echoes_the_argument(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _patches(graph)
        _ = _rereads(graph, _page_payload(title="Untouched by the argument"))

        answer = await _edit(
            client,
            commands=[EditCommand(target="body", action="append", content="<p>ignored</p>")],
        )

        assert "ignored" not in answer.model_dump_json()
        assert answer.title == "Untouched by the argument"

    async def test_nulls_when_graph_names_no_parent_section_or_notebook(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _patches(graph)
        _ = _rereads(graph, _page_payload(section=None, notebook=None))

        answer = await _edit(client)

        assert answer.section_uri is None
        assert answer.section_name is None
        assert answer.notebook_name is None

    async def test_a_reread_that_names_no_id_is_a_programming_error(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _patches(graph)
        _ = _rereads(graph, _page_payload(page_id=None))

        with pytest.raises(AssertionError):
            _ = await _edit(client)


class TestGraphFailures:
    async def test_a_404_on_the_patch_is_a_not_found_and_the_page_is_never_reread(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        page_route = graph.get(_GET_PATH).mock(
            return_value=httpx.Response(200, json=_page_payload())
        )
        patch = graph.post(_PATCH_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _edit(client)

        assert patch.call_count == 1
        assert page_route.call_count == 1, "only the pre-read happened; the patch never reread"

    async def test_a_404_on_the_notebook_read_is_a_not_found_and_nothing_is_patched(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        page_route = graph.get(_GET_PATH).mock(
            return_value=httpx.Response(200, json=_page_payload(notebook=_NOTEBOOK))
        )
        notebook_route = graph.get(_NOTEBOOK_GET_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )
        patch = graph.post(_PATCH_PATH).mock(return_value=httpx.Response(204))

        with pytest.raises(GraphNotFound):
            _ = await _edit(client)

        assert page_route.call_count == 1
        assert notebook_route.call_count == 1
        assert patch.call_count == 0, "the notebook read failed before anything was changed"

    async def test_a_403_on_the_patch_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_GET_PATH).mock(return_value=httpx.Response(200, json=_page_payload()))
        _ = graph.post(_PATCH_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _edit(client)

    async def test_a_404_on_the_reread_is_a_not_found_and_the_patch_was_sent_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _patches(graph, status=204)
        reread = graph.get(_GET_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_page_payload()),
                httpx.Response(
                    404, json={"error": {"code": "itemNotFound", "message": "not found"}}
                ),
            ]
        )

        with pytest.raises(GraphNotFound):
            _ = await _edit(client)

        assert patch.call_count == 1
        assert reread.call_count == 2, "the pre-read succeeded; the post-write reread failed"

    async def test_the_call_example_reaches_graph_and_the_pre_read_is_what_a_403_refuses(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        example = editor.GRAPH_CALL_EXAMPLE
        page = cast("str", example["page"])
        handle = onenote_page_handle(page)
        assert handle is not None, "GRAPH_CALL_EXAMPLE's own page value is not a page handle"
        raw_commands = cast("Sequence[Mapping[str, object]]", example["commands"])
        commands = [EditCommand.model_validate(dict(one)) for one in raw_commands]
        refused = graph.get(f"/me/onenote/pages/{handle.page_id}").mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await edit_page(client, page=page, commands=commands, confirm=_agrees)

        assert refused.call_count == 1


class TestThePersonBetweenTheEditAndTheOthersInTheNotebook:
    async def test_append_only_commands_in_a_private_notebook_ask_no_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _rereads(graph, _page_payload(notebook=_NOTEBOOK))
        _ = _notebook_route(graph, is_shared=False, user_role="Owner")
        patch = _patches(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _edit(client, commands=[_APPEND_COMMAND], confirm=counting)

        assert asked == [], "an append-only command set in a private notebook needs no question"
        assert patch.call_count == 1

    async def test_a_replace_command_is_asked_about_even_in_a_private_notebook(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _rereads(graph, _page_payload(notebook=_NOTEBOOK))
        _ = _notebook_route(graph, is_shared=False, user_role="Owner")
        patch = _patches(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _edit(client, commands=[_REPLACE_COMMAND], confirm=counting)

        assert len(asked) == 1, "a replace command must always be confirmed"
        assert "cannot be undone" in asked[0]
        assert patch.call_count == 1

    async def test_a_delete_command_is_asked_about_even_in_a_private_notebook(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _rereads(graph, _page_payload(notebook=_NOTEBOOK))
        _ = _notebook_route(graph, is_shared=False, user_role="Owner")
        patch = _patches(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _edit(client, commands=[_DELETE_COMMAND], confirm=counting)

        assert len(asked) == 1
        assert "cannot be undone" in asked[0]
        assert patch.call_count == 1

    async def test_the_warning_is_absent_when_every_command_is_non_destructive(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _rereads(graph, _page_payload(notebook=_NOTEBOOK))
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        _ = _patches(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _edit(client, commands=[_APPEND_COMMAND], confirm=capturing)

        assert "cannot be undone" not in asked[0]

    async def test_a_shared_notebook_is_asked_about_and_a_refusal_changes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        page_route = _rereads(graph, _page_payload(notebook=_NOTEBOOK))
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        patch = _patches(graph)

        with pytest.raises(ToolError, match="Nothing was changed"):
            _ = await _edit(client, confirm=_refuses)

        assert patch.call_count == 0
        assert page_route.call_count == 1, "only the pre-read happened; the reread never followed"

    async def test_a_notebook_the_user_does_not_own_is_asked_about(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _rereads(graph, _page_payload(notebook=_NOTEBOOK))
        _ = _notebook_route(graph, is_shared=False, user_role="Contributor")
        patch = _patches(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _edit(client, confirm=counting)

        assert len(asked) == 1
        assert patch.call_count == 1

    async def test_a_page_whose_notebook_graph_does_not_name_is_asked_about(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _rereads(graph, _page_payload(notebook=None))
        patch = _patches(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _edit(client, confirm=counting)

        assert len(asked) == 1, "an unnamed notebook was written to without asking anybody"
        assert patch.call_count == 1

    async def test_the_question_names_the_title_notebook_reason_count_and_first_command(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _rereads(graph, _page_payload(title="Meeting notes", notebook=_NOTEBOOK))
        _ = _notebook_route(graph, is_shared=True, user_role="Owner", name="Work")
        _ = _patches(graph)
        asked: list[str] = []
        bound: list[str] = []
        commands = [
            EditCommand(target="body", action="append", content="<p>Agenda: pricing</p>"),
            EditCommand(target="#p2", action="delete"),
        ]

        async def capturing(question: str, about: str) -> str | None:
            asked.append(question)
            bound.append(about)
            return None

        _ = await _edit(client, commands=commands, confirm=capturing)

        assert len(asked) == 1
        question = asked[0]
        assert "Meeting notes" in question
        assert "Work" in question
        assert "shared with other people" in question
        assert "2 commands" in question
        assert "appends" in question
        assert "'body'" in question
        assert "Agenda: pricing" in question
        assert bound == [
            write_state_for(
                "edit",
                _PAGE_ID,
                json.dumps([command.model_dump() for command in commands], sort_keys=True),
            )
        ]

    async def test_the_question_names_who_the_notebook_belongs_to_when_it_is_not_the_user(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _rereads(graph, _page_payload(notebook=_NOTEBOOK))
        _ = _notebook_route(graph, is_shared=False, user_role="Contributor", name="Work")
        _ = _patches(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _edit(client, confirm=capturing)

        assert "belongs to somebody else" in asked[0]
        assert "Contributor" in asked[0]

    async def test_the_question_names_no_notebook_or_page_graph_left_unnamed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _rereads(graph, _page_payload(title=None, notebook=None))
        _ = _patches(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _edit(client, confirm=capturing)

        assert "an untitled page" in asked[0]
        assert "an unnamed notebook" in asked[0]
        assert "whose sharing Microsoft did not report" in asked[0]

    async def test_about_is_the_same_for_two_identical_calls_and_different_for_changed_commands(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _rereads(graph, _page_payload(notebook=_NOTEBOOK))
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        _ = _patches(graph)
        bound: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert question
            bound.append(about)
            return None

        same = [EditCommand(target="body", action="append", content="<p>same</p>")]
        different = [EditCommand(target="body", action="append", content="<p>different</p>")]

        _ = await _edit(client, commands=same, confirm=capturing)
        _ = await _edit(client, commands=same, confirm=capturing)
        _ = await _edit(client, commands=different, confirm=capturing)

        assert bound[0] == bound[1]
        assert bound[2] != bound[0]

    @pytest.mark.parametrize(
        "answer",
        [
            DeclinedElicitation(),
            CancelledElicitation(),
            AcceptedElicitation(data="do not edit"),
            RuntimeError("elicitation not supported"),
            ToolError("the client refused the request"),
        ],
        ids=["declined", "cancelled", "another-answer", "cannot-ask", "client-error"],
    )
    async def test_no_refusal_is_ever_raised(self, answer: object) -> None:
        confirm = a_person_agrees(_context(answer))

        refusal = await confirm("Change the page 'Meeting notes' in 'Work'?", "synthetic-state")

        assert isinstance(refusal, str)
        assert refusal

    async def test_a_refusal_this_tool_words_opens_by_saying_nothing_was_changed(self) -> None:
        confirm = a_person_agrees(_context(DeclinedElicitation()))

        refusal = await confirm("Change the page 'Meeting notes' in 'Work'?", "synthetic-state")

        assert isinstance(refusal, str)
        assert refusal.startswith("Nothing was changed.")

    async def test_agreeing_answers_with_no_refusal(self) -> None:
        confirm = a_person_agrees(_context(AcceptedElicitation(data="edit")))

        assert await confirm("Change the page 'Meeting notes'?", "synthetic-state") is None


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
        _ = _rereads(graph, _page_payload(notebook=_NOTEBOOK))
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        patch = _patches(graph)
        commands = [_APPEND_COMMAND]

        answer = await edit_page(
            client,
            page=_PAGE_URI,
            commands=commands,
            confirm=a_person_agrees(_modern_context()),
        )

        assert isinstance(answer, InputRequiredResult)
        assert answer.request_state == write_state_for(
            "edit",
            _PAGE_ID,
            json.dumps([command.model_dump() for command in commands], sort_keys=True),
        )
        assert patch.call_count == 0

    async def test_the_first_round_asks_the_question_this_tool_words(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _rereads(graph, _page_payload(notebook=_NOTEBOOK))
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        _ = _patches(graph)

        answer = await edit_page(
            client,
            page=_PAGE_URI,
            commands=[_APPEND_COMMAND],
            confirm=a_person_agrees(_modern_context()),
        )

        assert isinstance(answer, InputRequiredResult)
        requests = answer.input_requests or {}
        request = requests[next(iter(requests))]
        assert isinstance(request, ElicitRequest)
        params = request.params
        assert isinstance(params, ElicitRequestFormParams)
        assert "Meeting notes" in params.message
        assert "Work" in params.message

    async def test_the_second_round_edits_under_the_id_it_was_agreed_to_by(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _rereads(graph, _page_payload(notebook=_NOTEBOOK))
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        patch = _patches(graph)
        commands = [_APPEND_COMMAND]
        state = write_state_for(
            "edit",
            _PAGE_ID,
            json.dumps([command.model_dump() for command in commands], sort_keys=True),
        )

        first = await edit_page(
            client,
            page=_PAGE_URI,
            commands=commands,
            confirm=a_person_agrees(_modern_context()),
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))

        answer = await edit_page(
            client,
            page=_PAGE_URI,
            commands=commands,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": "edit"})},
                    state=state,
                )
            ),
        )

        assert isinstance(answer, PageSummary)
        assert patch.call_count == 1

    async def test_an_answer_bound_to_another_request_changes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _rereads(graph, _page_payload(notebook=_NOTEBOOK))
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        patch = _patches(graph)

        first = await edit_page(
            client,
            page=_PAGE_URI,
            commands=[_APPEND_COMMAND],
            confirm=a_person_agrees(_modern_context()),
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await edit_page(
                client,
                page=_PAGE_URI,
                commands=[_APPEND_COMMAND],
                confirm=a_person_agrees(
                    _modern_context(
                        answers={key: ElicitResult(action="accept", content={"value": "edit"})},
                        state="synthetic-other-state",
                    )
                ),
            )

        assert patch.call_count == 0

    async def test_a_pending_decline_is_honored_even_when_the_fresh_read_says_private_append_only(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _rereads(graph, _page_payload(notebook=_NOTEBOOK))
        notebook_route = graph.get(_NOTEBOOK_GET_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_notebook_payload(is_shared=True, user_role="Owner")),
                httpx.Response(200, json=_notebook_payload(is_shared=False, user_role="Owner")),
            ]
        )
        patch = _patches(graph)

        first = await edit_page(
            client,
            page=_PAGE_URI,
            commands=[_APPEND_COMMAND],
            confirm=a_person_agrees(_modern_context()),
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))
        state = first.request_state
        assert state is not None

        with pytest.raises(ToolError, match="Nothing was changed"):
            _ = await edit_page(
                client,
                page=_PAGE_URI,
                commands=[_APPEND_COMMAND],
                confirm=a_person_agrees(
                    _modern_context(answers={key: ElicitResult(action="decline")}, state=state)
                ),
                answer_pending=True,
            )

        assert patch.call_count == 0
        assert notebook_route.call_count == 2

    async def test_a_pending_accept_still_edits_when_the_fresh_read_says_private(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _rereads(graph, _page_payload(notebook=_NOTEBOOK))
        notebook_route = graph.get(_NOTEBOOK_GET_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_notebook_payload(is_shared=True, user_role="Owner")),
                httpx.Response(200, json=_notebook_payload(is_shared=False, user_role="Owner")),
            ]
        )
        patch = _patches(graph)

        first = await edit_page(
            client,
            page=_PAGE_URI,
            commands=[_APPEND_COMMAND],
            confirm=a_person_agrees(_modern_context()),
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))
        state = first.request_state
        assert state is not None

        answer = await edit_page(
            client,
            page=_PAGE_URI,
            commands=[_APPEND_COMMAND],
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": "edit"})},
                    state=state,
                )
            ),
            answer_pending=True,
        )

        assert isinstance(answer, PageSummary)
        assert patch.call_count == 1
        assert notebook_route.call_count == 2


class TestTheClientThatCannotAsk:
    async def test_a_client_that_cannot_ask_changes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _rereads(graph, _page_payload(notebook=_NOTEBOOK))
        _ = _notebook_route(graph, is_shared=True, user_role="Owner")
        patch = _patches(graph)

        class _CannotAsk:
            request_context: object = None

            async def elicit(self, message: str, response_type: object = None) -> object:
                assert message and response_type is not None
                raise RuntimeError("elicitation not supported")

        confirm = a_person_agrees(cast("Context", cast("object", _CannotAsk())))

        with pytest.raises(ToolError, match="does not support elicitation"):
            _ = await edit_page(client, page=_PAGE_URI, commands=[_APPEND_COMMAND], confirm=confirm)

        assert patch.call_count == 0


class TestHowRegisterWiresThePendingAnswer:
    async def test_register_consults_a_pending_answer_the_fresh_read_alone_would_skip(
        self, transport: httpx.AsyncClient, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _rereads(graph, _page_payload(notebook=_NOTEBOOK))
        notebook_route = graph.get(_NOTEBOOK_GET_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_notebook_payload(is_shared=True, user_role="Owner")),
                httpx.Response(200, json=_notebook_payload(is_shared=False, user_role="Owner")),
            ]
        )
        patch = _patches(graph)
        mcp: FastMCP = FastMCP(name="wiring-under-test")
        editor.register(mcp, transport)
        tool = await mcp.get_tool(editor.TOOL_NAME)
        assert tool is not None, "register left the tool off the server"
        assert isinstance(tool, FunctionTool)

        first = cast(
            "PageSummary | InputRequiredResult",
            await tool.fn(
                page=_PAGE_URI,
                commands=[_APPEND_COMMAND],
                ctx=_modern_context(),
                client=client,
            ),
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))
        state = first.request_state
        assert state is not None

        with pytest.raises(ToolError, match="Nothing was changed"):
            _ = cast(
                "PageSummary | InputRequiredResult",
                await tool.fn(
                    page=_PAGE_URI,
                    commands=[_APPEND_COMMAND],
                    ctx=_modern_context(answers={key: ElicitResult(action="decline")}, state=state),
                    client=client,
                ),
            )

        assert patch.call_count == 0
        assert notebook_route.call_count == 2


class TestHowItDeclaresItself:
    def test_the_permission_is_notes_readwrite(self) -> None:
        assert editor.GRAPH_PERMISSIONS == ("Notes.ReadWrite",)

    def test_the_call_example_is_a_page_handle_and_commands(self) -> None:
        assert set(editor.GRAPH_CALL_EXAMPLE) == {"page", "commands"}

    async def test_the_call_example_is_accepted_by_the_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(editor.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_it_takes_two_arguments_and_no_others(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"page", "commands"}

    @pytest.mark.parametrize("word", ["client", "ctx", "context", "token", "graph"])
    async def test_no_wiring_of_this_server_is_published_as_an_argument(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_it_announces_itself_as_a_destructive_write(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None, (
            "a tool with no annotations joins the write surface by omission"
        )
        assert annotations.read_only_hint is WRITE_DESTRUCTIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_DESTRUCTIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_DESTRUCTIVE["idempotentHint"]

    async def test_the_description_carries_the_element_action_matrix(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = (tool.description or "").casefold()
        for word in (
            "body",
            "div",
            "img",
            "object",
            "ol",
            "ul",
            "table",
            "title",
            "onenote_rename_page",
            "onenote_read_page",
            "include_ids",
            "tr",
            "td",
            "meta",
            "head",
            "span",
            "style",
            "not safe to retry blindly",
        ):
            assert word in description, f"{word!r} is missing from the description"

    def test_not_found_advice_points_at_the_lister(self) -> None:
        assert "onenote_list_pages" in editor.GRAPH_NOT_FOUND
