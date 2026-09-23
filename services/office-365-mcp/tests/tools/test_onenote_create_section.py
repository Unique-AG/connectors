import json
from collections.abc import Mapping
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import AcceptedElicitation, DeclinedElicitation
from fastmcp.tools import FunctionTool
from mcp.types import ElicitResult, InputRequiredResult, InputResponse
from mcp.types.version import LATEST_MODERN_VERSION
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound, GraphUnavailable
from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    OnenotePageHandle,
    OnenoteSectionGroupHandle,
    OnenoteSectionHandle,
)
from office_365_mcp.shared.notes import write_state_for
from office_365_mcp.shared.seam import Confirm
from office_365_mcp.tools import onenote_create_section as creator
from office_365_mcp.tools.onenote_create_section import a_person_agrees, create_section

_NOTEBOOK_ID = "1-SYNTHETICNOTEBOOK0001!0001"
_GROUP_ID = "1-SYNTHETICGROUP0001!0001"
_SECTION_ID = "1-SYNTHETICSECTION0001!0001"

_NOTEBOOK = OnenoteNotebookHandle(_NOTEBOOK_ID).uri
_GROUP = OnenoteSectionGroupHandle(_GROUP_ID).uri

_NAME = "Synthetic section"

_NOTEBOOK_AUDIENCE_PATH = f"/me/onenote/notebooks/{_NOTEBOOK_ID}"
_GROUP_AUDIENCE_PATH = f"/me/onenote/sectionGroups/{_GROUP_ID}"
_NOTEBOOK_SECTIONS_PATH = f"/me/onenote/notebooks/{_NOTEBOOK_ID}/sections"
_GROUP_SECTIONS_PATH = f"/me/onenote/sectionGroups/{_GROUP_ID}/sections"


def _notebook_payload(
    *,
    notebook_id: str = _NOTEBOOK_ID,
    name: str | None = "Work",
    is_shared: bool | None = False,
    user_role: str | None = "Owner",
) -> dict[str, object]:
    return {"id": notebook_id, "displayName": name, "isShared": is_shared, "userRole": user_role}


def _section_payload(
    *,
    section_id: str | None = _SECTION_ID,
    name: str | None = "Synthetic section",
    is_default: bool | None = False,
    web_url: str | None = "https://onenote.example.invalid/sections/synthetic",
    client_url: str | None = "onenote:https://onenote.example.invalid/sections/synthetic",
    created_at: str | None = "2026-03-01T09:00:00Z",
) -> dict[str, object]:
    return {
        "id": section_id,
        "displayName": name,
        "isDefault": is_default,
        "links": {
            "oneNoteWebUrl": {"href": web_url} if web_url is not None else None,
            "oneNoteClientUrl": {"href": client_url} if client_url is not None else None,
        },
        "createdDateTime": created_at,
    }


@pytest.fixture
def notebook_audience(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_NOTEBOOK_AUDIENCE_PATH).mock(
        return_value=httpx.Response(200, json=_notebook_payload())
    )


@pytest.fixture
def group_audience(graph: respx.MockRouter) -> respx.Route:
    _ = graph.get(_NOTEBOOK_AUDIENCE_PATH).mock(
        return_value=httpx.Response(200, json=_notebook_payload())
    )
    return graph.get(_GROUP_AUDIENCE_PATH).mock(
        return_value=httpx.Response(
            200, json={"id": _GROUP_ID, "parentNotebook": {"id": _NOTEBOOK_ID}}
        )
    )


@pytest.fixture
def notebook_sections(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_NOTEBOOK_SECTIONS_PATH).mock(
        return_value=httpx.Response(201, json=_section_payload())
    )


@pytest.fixture
def group_sections(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_GROUP_SECTIONS_PATH).mock(
        return_value=httpx.Response(201, json=_section_payload())
    )


async def _agrees(question: str, about: str) -> str | None:
    assert question
    assert about
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return "No section was created."


async def _create(
    client: GraphServiceClient,
    *,
    parent: str = _NOTEBOOK,
    name: str = _NAME,
    confirm: Confirm = _agrees,
) -> creator.CreatedSection:
    answer = await create_section(client, parent=parent, name=name, confirm=confirm)
    assert isinstance(answer, creator.CreatedSection), (
        "this call was answered with a question, not a section"
    )
    return answer


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


class TestWhatItSendsToGraph:
    @pytest.mark.usefixtures("notebook_audience")
    async def test_a_notebook_parent_reads_the_notebook_audience_and_posts_under_it(
        self,
        client: GraphServiceClient,
        notebook_sections: respx.Route,
        group_sections: respx.Route,
    ) -> None:
        _ = await _create(client, parent=_NOTEBOOK)

        assert notebook_sections.call_count == 1
        assert group_sections.call_count == 0

    @pytest.mark.usefixtures("group_audience")
    async def test_a_group_parent_reads_the_group_audience_and_posts_under_it(
        self,
        client: GraphServiceClient,
        notebook_sections: respx.Route,
        group_sections: respx.Route,
    ) -> None:
        _ = await _create(client, parent=_GROUP)

        assert group_sections.call_count == 1
        assert notebook_sections.call_count == 0

    @pytest.mark.usefixtures("notebook_audience")
    async def test_the_post_carries_only_the_display_name(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        _ = await _create(client, parent=_NOTEBOOK, name="A new section")

        assert _sent(notebook_sections)["displayName"] == "A new section"

    @pytest.mark.usefixtures("notebook_audience")
    async def test_the_content_type_is_json(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        _ = await _create(client, parent=_NOTEBOOK)

        assert notebook_sections.calls.last.request.headers["content-type"] == "application/json"

    @pytest.mark.usefixtures("retry_sleeps", "notebook_audience")
    async def test_a_create_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = graph.post(_NOTEBOOK_SECTIONS_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _create(client, parent=_NOTEBOOK)

        assert post.call_count == 1, "no_retry means one attempt, however Graph answers"


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            "Work",
            "https://onenote.example.invalid/notebooks/team",
            _NOTEBOOK_ID,
            "onenote:///notebooks/",
            OnenoteSectionHandle(_SECTION_ID).uri,
            OnenotePageHandle("0-SYNTHETICPAGE0001!0001").uri,
        ],
    )
    async def test_a_value_that_is_neither_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError):
            _ = await _create(client, parent=value)

        assert len(graph.calls) == 0

    async def test_the_refusal_names_both_shapes_and_where_each_comes_from(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="onenote_list_notebooks") as excinfo:
            _ = await _create(client, parent="Work")

        message = str(excinfo.value)
        assert "onenote_find_notebook_from_url" in message
        assert "onenote_list_sections" in message
        assert "onenote_create_section_group" in message


class TestWhatItAnswers:
    @pytest.mark.usefixtures("notebook_audience")
    async def test_the_answer_carries_the_new_sections_handle_and_fields(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        notebook_sections.mock(
            return_value=httpx.Response(201, json=_section_payload(name="Stored Name"))
        )

        answer = await _create(client, parent=_NOTEBOOK)

        assert answer.uri == OnenoteSectionHandle(_SECTION_ID).uri
        assert answer.name == "Stored Name"
        assert answer.is_default is False
        assert answer.web_url == "https://onenote.example.invalid/sections/synthetic"
        assert answer.client_url == "onenote:https://onenote.example.invalid/sections/synthetic"
        assert answer.created_at is not None
        assert answer.parent_uri == _NOTEBOOK

    @pytest.mark.usefixtures("group_audience", "group_sections")
    async def test_a_group_parent_answers_with_that_groups_uri(
        self, client: GraphServiceClient
    ) -> None:
        answer = await _create(client, parent=_GROUP)

        assert answer.parent_uri == _GROUP

    @pytest.mark.usefixtures("notebook_audience")
    async def test_the_answer_is_read_off_graph_and_never_echoes_the_argument(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        notebook_sections.mock(
            return_value=httpx.Response(201, json=_section_payload(name="Untouched by argument"))
        )

        answer = await _create(client, parent=_NOTEBOOK, name="something else entirely")

        assert "something else entirely" not in answer.model_dump_json()
        assert answer.name == "Untouched by argument"

    @pytest.mark.usefixtures("notebook_audience")
    async def test_a_create_that_names_no_id_is_a_programming_error(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        notebook_sections.mock(
            return_value=httpx.Response(201, json=_section_payload(section_id=None))
        )

        with pytest.raises(AssertionError):
            _ = await _create(client, parent=_NOTEBOOK)


class TestGraphFailures:
    def test_the_permission_is_notes_create(self) -> None:
        assert creator.GRAPH_PERMISSIONS == ("Notes.Create",)

    @pytest.mark.usefixtures("notebook_audience")
    async def test_a_403_on_the_post_is_a_forbidden(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        notebook_sections.mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _create(client, parent=_NOTEBOOK)

    async def test_a_404_on_the_notebook_audience_read_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter, notebook_sections: respx.Route
    ) -> None:
        _ = graph.get(_NOTEBOOK_AUDIENCE_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _create(client, parent=_NOTEBOOK)

        assert notebook_sections.call_count == 0

    def test_the_not_found_advice_covers_both_shapes(self) -> None:
        assert "onenote_list_notebooks" in creator.GRAPH_NOT_FOUND
        assert "onenote_list_sections" in creator.GRAPH_NOT_FOUND


class TestThePersonBetweenTheCreateAndTheOthersInTheNotebook:
    @pytest.mark.usefixtures("notebook_audience")
    async def test_the_users_own_unshared_notebook_is_written_to_without_a_question(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, parent=_NOTEBOOK, confirm=counting)

        assert asked == [], "the user's own private notebook was put to a person anyway"
        assert notebook_sections.call_count == 1

    async def test_a_shared_notebook_is_asked_about_and_a_refusal_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter, notebook_sections: respx.Route
    ) -> None:
        _ = graph.get(_NOTEBOOK_AUDIENCE_PATH).mock(
            return_value=httpx.Response(
                200, json=_notebook_payload(is_shared=True, user_role="Owner")
            )
        )

        with pytest.raises(ToolError, match="No section was created"):
            _ = await _create(client, parent=_NOTEBOOK, confirm=_refuses)

        assert notebook_sections.call_count == 0

    @pytest.mark.usefixtures("group_sections")
    async def test_a_section_group_parent_is_confirmed_from_its_owning_notebooks_audience(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_GROUP_AUDIENCE_PATH).mock(
            return_value=httpx.Response(
                200, json={"id": _GROUP_ID, "parentNotebook": {"id": _NOTEBOOK_ID}}
            )
        )
        _ = graph.get(_NOTEBOOK_AUDIENCE_PATH).mock(
            return_value=httpx.Response(
                200, json=_notebook_payload(is_shared=True, user_role="Owner")
            )
        )
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, parent=_GROUP, confirm=counting)

        assert len(asked) == 1
        assert "Work" in asked[0]
        assert "shared with other people" in asked[0]

    @pytest.mark.usefixtures("group_sections")
    async def test_the_question_names_the_section_group_when_the_parent_is_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_GROUP_AUDIENCE_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": _GROUP_ID,
                    "displayName": "Projects",
                    "parentNotebook": {"id": _NOTEBOOK_ID},
                },
            )
        )
        _ = graph.get(_NOTEBOOK_AUDIENCE_PATH).mock(
            return_value=httpx.Response(
                200, json=_notebook_payload(name="Work", is_shared=True, user_role="Owner")
            )
        )
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, parent=_GROUP, name="Synthetic section", confirm=capturing)

        assert len(asked) == 1
        assert "Synthetic section" in asked[0]
        assert "section group" in asked[0]
        assert "Projects" in asked[0]
        assert "Work" in asked[0]

    @pytest.mark.usefixtures("notebook_sections")
    async def test_the_question_names_the_section_and_the_notebook(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_NOTEBOOK_AUDIENCE_PATH).mock(
            return_value=httpx.Response(
                200, json=_notebook_payload(name="Work", is_shared=True, user_role="Owner")
            )
        )
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, parent=_NOTEBOOK, name="Synthetic section", confirm=capturing)

        assert len(asked) == 1
        assert "Synthetic section" in asked[0]
        assert "Work" in asked[0]

    @pytest.mark.usefixtures("notebook_sections")
    async def test_about_is_the_same_for_two_identical_calls_and_different_for_a_changed_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_NOTEBOOK_AUDIENCE_PATH).mock(
            return_value=httpx.Response(
                200, json=_notebook_payload(is_shared=True, user_role="Owner")
            )
        )
        bound: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert question
            bound.append(about)
            return None

        _ = await _create(client, parent=_NOTEBOOK, name="Same", confirm=capturing)
        _ = await _create(client, parent=_NOTEBOOK, name="Same", confirm=capturing)
        _ = await _create(client, parent=_NOTEBOOK, name="Different", confirm=capturing)

        assert bound[0] == bound[1]
        assert bound[2] != bound[0]
        assert bound[0] == write_state_for("create_section", _NOTEBOOK, "Same")


def _context(answer: object) -> Context:
    class _Client:
        request_context: object = None

        async def elicit(self, message: str, response_type: object = None) -> object:
            assert message
            assert response_type is not None
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
        self, client: GraphServiceClient, graph: respx.MockRouter, notebook_sections: respx.Route
    ) -> None:
        _ = graph.get(_NOTEBOOK_AUDIENCE_PATH).mock(
            return_value=httpx.Response(
                200, json=_notebook_payload(is_shared=True, user_role="Owner")
            )
        )

        answer = await create_section(
            client,
            parent=_NOTEBOOK,
            name=_NAME,
            confirm=a_person_agrees(_modern_context()),
        )

        assert isinstance(answer, InputRequiredResult)
        assert answer.request_state == write_state_for("create_section", _NOTEBOOK, _NAME)
        assert notebook_sections.call_count == 0

    async def test_the_second_round_creates_under_the_id_it_was_agreed_to_by(
        self, client: GraphServiceClient, graph: respx.MockRouter, notebook_sections: respx.Route
    ) -> None:
        _ = graph.get(_NOTEBOOK_AUDIENCE_PATH).mock(
            return_value=httpx.Response(
                200, json=_notebook_payload(is_shared=True, user_role="Owner")
            )
        )
        state = write_state_for("create_section", _NOTEBOOK, _NAME)

        first = await create_section(
            client,
            parent=_NOTEBOOK,
            name=_NAME,
            confirm=a_person_agrees(_modern_context()),
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))

        answer = await create_section(
            client,
            parent=_NOTEBOOK,
            name=_NAME,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": "create"})},
                    state=state,
                )
            ),
        )

        assert isinstance(answer, creator.CreatedSection)
        assert notebook_sections.call_count == 1

    async def test_a_pending_decline_is_honored_even_when_the_fresh_read_says_private(
        self, client: GraphServiceClient, graph: respx.MockRouter, notebook_sections: respx.Route
    ) -> None:
        notebook_route = graph.get(_NOTEBOOK_AUDIENCE_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_notebook_payload(is_shared=True, user_role="Owner")),
                httpx.Response(200, json=_notebook_payload(is_shared=False, user_role="Owner")),
            ]
        )

        first = await create_section(
            client,
            parent=_NOTEBOOK,
            name=_NAME,
            confirm=a_person_agrees(_modern_context()),
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))
        state = first.request_state
        assert state is not None

        with pytest.raises(ToolError, match="No section was created"):
            _ = await create_section(
                client,
                parent=_NOTEBOOK,
                name=_NAME,
                confirm=a_person_agrees(
                    _modern_context(answers={key: ElicitResult(action="decline")}, state=state)
                ),
                answer_pending=True,
            )

        assert notebook_sections.call_count == 0
        assert notebook_route.call_count == 2

    async def test_a_pending_accept_still_creates_when_the_fresh_read_says_private(
        self, client: GraphServiceClient, graph: respx.MockRouter, notebook_sections: respx.Route
    ) -> None:
        notebook_route = graph.get(_NOTEBOOK_AUDIENCE_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_notebook_payload(is_shared=True, user_role="Owner")),
                httpx.Response(200, json=_notebook_payload(is_shared=False, user_role="Owner")),
            ]
        )

        first = await create_section(
            client,
            parent=_NOTEBOOK,
            name=_NAME,
            confirm=a_person_agrees(_modern_context()),
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))
        state = first.request_state
        assert state is not None

        answer = await create_section(
            client,
            parent=_NOTEBOOK,
            name=_NAME,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": "create"})},
                    state=state,
                )
            ),
            answer_pending=True,
        )

        assert isinstance(answer, creator.CreatedSection)
        assert notebook_sections.call_count == 1
        assert notebook_route.call_count == 2


class TestHowRegisterWiresThePendingAnswer:
    async def test_register_consults_a_pending_answer_the_fresh_read_alone_would_skip(
        self, transport: httpx.AsyncClient, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        notebook_route = graph.get(_NOTEBOOK_AUDIENCE_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_notebook_payload(is_shared=True, user_role="Owner")),
                httpx.Response(200, json=_notebook_payload(is_shared=False, user_role="Owner")),
            ]
        )
        post = graph.post(_NOTEBOOK_SECTIONS_PATH).mock(
            return_value=httpx.Response(201, json=_section_payload())
        )
        mcp: FastMCP = FastMCP(name="wiring-under-test")
        creator.register(mcp, transport)
        tool = await mcp.get_tool(creator.TOOL_NAME)
        assert tool is not None, "register left the tool off the server"
        assert isinstance(tool, FunctionTool)

        first = cast(
            "creator.CreatedSection | InputRequiredResult",
            await tool.fn(parent=_NOTEBOOK, name=_NAME, ctx=_modern_context(), client=client),
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))
        state = first.request_state
        assert state is not None

        with pytest.raises(ToolError, match="No section was created"):
            _ = cast(
                "creator.CreatedSection | InputRequiredResult",
                await tool.fn(
                    parent=_NOTEBOOK,
                    name=_NAME,
                    ctx=_modern_context(answers={key: ElicitResult(action="decline")}, state=state),
                    client=client,
                ),
            )

        assert post.call_count == 0
        assert notebook_route.call_count == 2


class TestNoRefusalIsEverRaisedByThePrompt:
    @pytest.mark.parametrize(
        "answer",
        [DeclinedElicitation(), AcceptedElicitation(data="do not create")],
        ids=["declined", "another-answer"],
    )
    async def test_no_refusal_is_ever_raised(self, answer: object) -> None:
        confirm = a_person_agrees(_context(answer))

        refusal = await confirm("Create the section 'X' in the notebook 'Y'?", "synthetic-state")

        assert isinstance(refusal, str)
        assert refusal.startswith("No section was created.")

    async def test_agreeing_answers_with_no_refusal(self) -> None:
        confirm = a_person_agrees(_context(AcceptedElicitation(data="create")))

        assert (
            await confirm("Create the section 'X' in the notebook 'Y'?", "synthetic-state") is None
        )
