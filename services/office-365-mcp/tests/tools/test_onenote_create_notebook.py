import json
from collections.abc import Mapping
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Client, Context, FastMCP
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
)
from fastmcp.tools import FunctionTool, Tool
from mcp.shared.exceptions import MCPError
from mcp.types import METHOD_NOT_FOUND, ElicitResult, InputRequiredResult, InputResponse
from mcp.types.version import LATEST_MODERN_VERSION
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphFailure, GraphForbidden, GraphNotFound
from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    OnenoteOwner,
    onenote_notebook_handle,
)
from office_365_mcp.shared.notes import named_owner_refused, write_state_for
from office_365_mcp.shared.seam import WRITE_ADDITIVE, Advised, Confirm, GraphAdviceMiddleware
from office_365_mcp.tools import graph_advice, resolve
from office_365_mcp.tools import onenote_create_notebook as creator
from office_365_mcp.tools.onenote_create_notebook import a_person_agrees, create_notebook

_NOTEBOOKS_PATH = "/me/onenote/notebooks"

_NOTEBOOK_ID = "1-SYNTHETICNOTEBOOK0001!0001"

_GROUP_ID = "2b7c9d10-4e5f-4a6b-8c7d-9e0f1a2b3c4d"

_GROUP_NOTEBOOKS_PATH = f"/groups/{_GROUP_ID}/onenote/notebooks"

_SITE_ID = (
    "contoso.sharepoint.invalid,0d1e2f3a-0000-4000-8000-000000000001,"
    + "4b5c6d7e-0000-4000-8000-000000000002"
)

_SITE_NOTEBOOKS_PATH = f"/sites/{_SITE_ID}/onenote/notebooks"

_NAME = "My Notebook"


def _notebook_payload(
    *,
    notebook_id: str | None = _NOTEBOOK_ID,
    name: str | None = "My Notebook",
    is_default: bool | None = True,
    is_shared: bool | None = False,
    user_role: str | None = "Owner",
    web_url: str | None = "https://onenote.example.invalid/notebooks/my-notebook",
    client_url: str | None = "onenote:https://onenote.example.invalid/notebooks/my-notebook",
    created_at: str | None = "2026-03-01T09:00:00Z",
) -> dict[str, object]:
    return {
        "id": notebook_id,
        "displayName": name,
        "isDefault": is_default,
        "isShared": is_shared,
        "userRole": user_role,
        "links": {
            "oneNoteWebUrl": {"href": web_url} if web_url is not None else None,
            "oneNoteClientUrl": {"href": client_url} if client_url is not None else None,
        },
        "createdDateTime": created_at,
    }


@pytest.fixture
def notebooks(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_NOTEBOOKS_PATH)


@pytest.fixture
def group_notebooks(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_GROUP_NOTEBOOKS_PATH).mock(
        return_value=httpx.Response(201, json=_notebook_payload(is_default=False))
    )


@pytest.fixture
def site_notebooks(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_SITE_NOTEBOOKS_PATH).mock(
        return_value=httpx.Response(201, json=_notebook_payload(is_default=False))
    )


async def _agrees(question: str, about: str) -> str | None:
    assert question
    assert about
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return "No notebook was created."


async def _create(
    client: GraphServiceClient,
    *,
    name: str = _NAME,
    group: str | None = None,
    site: str | None = None,
    confirm: Confirm = _agrees,
) -> creator.CreatedNotebook:
    answer = await create_notebook(client, name=name, group=group, site=site, confirm=confirm)
    assert isinstance(answer, creator.CreatedNotebook), (
        "this call was answered with a question, not a notebook"
    )
    return answer


async def _told_through_the_advice(
    client: GraphServiceClient, *, group: str | None = None, site: str | None = None
) -> str:
    advice = GraphAdviceMiddleware(graph_advice(resolve(preset=None, enabled=[creator.TOOL_NAME])))
    server: FastMCP[None] = FastMCP("creator", middleware=[advice])

    @server.tool(name=creator.TOOL_NAME, annotations=WRITE_ADDITIVE)
    async def create() -> str:
        return (await _create(client, group=group, site=site)).uri

    async with Client(FastMCPTransport(server)) as mcp_client:
        with pytest.raises(ToolError) as raised:
            _ = await mcp_client.call_tool(creator.TOOL_NAME, {})
    return str(raised.value)


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


async def _registered(transport: httpx.AsyncClient) -> tuple[dict[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    creator.register(mcp, transport)
    tool = await mcp.get_tool(creator.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("dict[str, object]", tool.parameters), tool


class TestWhatItSendsToGraph:
    async def test_it_posts_a_display_name_and_nothing_else(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(return_value=httpx.Response(201, json=_notebook_payload()))

        _ = await _create(client, name="My Notebook")

        assert notebooks.call_count == 1
        assert _sent(notebooks)["displayName"] == "My Notebook"

    async def test_the_content_type_is_json(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(return_value=httpx.Response(201, json=_notebook_payload()))

        _ = await _create(client)

        assert notebooks.calls.last.request.headers["content-type"] == "application/json"

    async def test_a_group_create_posts_once_under_that_groups_onenote(
        self, client: GraphServiceClient, notebooks: respx.Route, group_notebooks: respx.Route
    ) -> None:
        _ = await _create(client, name="Team Notes", group=_GROUP_ID)

        assert group_notebooks.call_count == 1
        assert notebooks.call_count == 0
        assert _sent(group_notebooks)["displayName"] == "Team Notes"

    async def test_a_site_create_posts_once_under_that_sites_onenote_and_never_under_me(
        self, client: GraphServiceClient, notebooks: respx.Route, site_notebooks: respx.Route
    ) -> None:
        _ = await _create(client, name="Site Notes", site=_SITE_ID)

        assert site_notebooks.call_count == 1
        assert notebooks.call_count == 0
        assert _sent(site_notebooks)["displayName"] == "Site Notes"

    async def test_a_group_and_a_site_together_are_refused_before_any_question_or_graph_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        with pytest.raises(ToolError, match="at most one of `group` and `site`") as refused:
            _ = await _create(client, group=_GROUP_ID, site=_SITE_ID, confirm=counting)

        assert asked == []
        assert len(graph.calls) == 0
        assert "never to both" in str(refused.value)
        assert "do not retry it" in str(refused.value)

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_create_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(return_value=httpx.Response(503))

        with pytest.raises(GraphFailure):
            _ = await _create(client)

        assert notebooks.call_count == 1, "no_retry means one attempt, however Graph answers"

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_group_create_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, group_notebooks: respx.Route
    ) -> None:
        group_notebooks.mock(return_value=httpx.Response(503))

        with pytest.raises(GraphFailure):
            _ = await _create(client, group=_GROUP_ID)

        assert group_notebooks.call_count == 1, "no_retry means one attempt, however Graph answers"


class TestWhatItAnswers:
    async def test_the_answer_carries_the_new_notebooks_handle_and_fields(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(
            return_value=httpx.Response(
                201,
                json=_notebook_payload(
                    name="Stored Name", is_default=False, is_shared=False, user_role="Owner"
                ),
            )
        )

        answer = await _create(client)

        assert answer.uri == OnenoteNotebookHandle(_NOTEBOOK_ID).uri
        assert answer.name == "Stored Name"
        assert answer.is_default is False
        assert answer.is_shared is False
        assert answer.user_role == "Owner"
        assert answer.web_url == "https://onenote.example.invalid/notebooks/my-notebook"
        assert answer.client_url == "onenote:https://onenote.example.invalid/notebooks/my-notebook"
        assert answer.created_at is not None
        assert answer.created_at.isoformat() == "2026-03-01T09:00:00+00:00"

    @pytest.mark.usefixtures("group_notebooks")
    async def test_a_group_create_answers_with_a_handle_that_carries_the_group(
        self, client: GraphServiceClient
    ) -> None:
        answer = await _create(client, group=_GROUP_ID)

        assert (
            answer.uri
            == OnenoteNotebookHandle(_NOTEBOOK_ID, owner=OnenoteOwner("groups", _GROUP_ID)).uri
        )
        parsed = onenote_notebook_handle(answer.uri)
        assert parsed is not None
        assert parsed.owner == OnenoteOwner("groups", _GROUP_ID)
        assert parsed.notebook_id == _NOTEBOOK_ID

    @pytest.mark.usefixtures("site_notebooks")
    async def test_a_site_create_answers_with_a_handle_that_carries_the_site(
        self, client: GraphServiceClient
    ) -> None:
        answer = await _create(client, site=_SITE_ID)

        assert answer.uri.startswith("onenote:///sites/")
        assert (
            answer.uri
            == OnenoteNotebookHandle(_NOTEBOOK_ID, owner=OnenoteOwner("sites", _SITE_ID)).uri
        )
        parsed = onenote_notebook_handle(answer.uri)
        assert parsed is not None
        assert parsed.owner == OnenoteOwner("sites", _SITE_ID)
        assert parsed.notebook_id == _NOTEBOOK_ID

    async def test_the_answer_is_read_off_graph_and_never_echoes_the_argument(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(
            return_value=httpx.Response(201, json=_notebook_payload(name="Untouched by argument"))
        )

        answer = await _create(client, name="something else entirely")

        assert "something else entirely" not in answer.model_dump_json()
        assert answer.name == "Untouched by argument"

    async def test_nulls_when_graph_names_no_web_or_client_link(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(
            return_value=httpx.Response(201, json=_notebook_payload(web_url=None, client_url=None))
        )

        answer = await _create(client)

        assert answer.web_url is None
        assert answer.client_url is None

    async def test_a_create_that_names_no_id_is_a_programming_error(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(return_value=httpx.Response(201, json=_notebook_payload(notebook_id=None)))

        with pytest.raises(AssertionError):
            _ = await _create(client)


class TestGraphFailures:
    async def test_a_403_is_a_forbidden(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _create(client)

    @pytest.mark.parametrize(
        ("owner", "path"),
        [({"site": _SITE_ID}, _SITE_NOTEBOOKS_PATH), ({"group": _GROUP_ID}, _GROUP_NOTEBOOKS_PATH)],
        ids=["site", "group"],
    )
    async def test_a_403_for_a_named_owner_is_advised_with_the_owner_text(
        self, client: GraphServiceClient, graph: respx.MockRouter, owner: dict[str, str], path: str
    ) -> None:
        _ = graph.post(path).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(Advised) as advised:
            _ = await _create(client, group=owner.get("group"), site=owner.get("site"))

        assert str(advised.value).startswith(named_owner_refused("Notes.Create"))
        assert "are not the problem" not in str(advised.value)
        assert isinstance(advised.value.__cause__, GraphForbidden)

    async def test_a_403_for_a_site_reaches_the_client_as_the_owner_text(
        self, client: GraphServiceClient, site_notebooks: respx.Route
    ) -> None:
        site_notebooks.mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        told = await _told_through_the_advice(client, site=_SITE_ID)

        assert told.startswith(named_owner_refused("Notes.Create"))
        assert site_notebooks.call_count == 1

    async def test_a_404_for_a_group_reaches_the_client_as_the_not_found_text(
        self, client: GraphServiceClient, group_notebooks: respx.Route
    ) -> None:
        group_notebooks.mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _create(client, group=_GROUP_ID)
        told = await _told_through_the_advice(client, group=_GROUP_ID)

        assert told.startswith(creator.GRAPH_NOT_FOUND)

    def test_the_not_found_text_covers_a_group_a_site_and_neither(self) -> None:
        advice = creator.GRAPH_NOT_FOUND

        assert "For a `group` or a `site`" in advice
        assert (
            "names nothing that the signed-in user can reach. Ask the user for the correct id."
            in advice
        )
        assert "teams_list_my_teams" not in advice
        assert "This same id fails again, so do not retry it." in advice
        assert "Without `group` or `site`, Microsoft most likely found no OneNote" in advice

    async def test_a_409_duplicate_name_is_a_generic_graph_failure(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(
            return_value=httpx.Response(
                409, json={"error": {"code": "20117", "message": "already exists"}}
            )
        )

        with pytest.raises(GraphFailure):
            _ = await _create(client)

    async def test_the_call_example_reaches_graph_without_a_question(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(return_value=httpx.Response(201, json=_notebook_payload()))
        example = cast("dict[str, str]", creator.GRAPH_CALL_EXAMPLE)

        answer = await create_notebook(
            client, name=example["name"], confirm=a_person_agrees(_modern_context())
        )

        assert isinstance(answer, creator.CreatedNotebook)
        assert notebooks.call_count == 1


class TestThePersonBetweenTheCreateAndTheGroup:
    async def test_a_create_without_a_group_asks_nobody_and_posts_to_the_users_own_onenote(
        self, client: GraphServiceClient, notebooks: respx.Route, group_notebooks: respx.Route
    ) -> None:
        notebooks.mock(return_value=httpx.Response(201, json=_notebook_payload()))
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, confirm=counting)

        assert asked == [], "a notebook in the user's own OneNote was put to a person anyway"
        assert notebooks.call_count == 1
        assert group_notebooks.call_count == 0

    async def test_a_group_create_asks_once_before_it_posts(
        self, client: GraphServiceClient, group_notebooks: respx.Route
    ) -> None:
        posts_when_asked: list[int] = []

        async def counting(question: str, about: str) -> str | None:
            assert question
            assert about
            posts_when_asked.append(group_notebooks.call_count)
            return None

        _ = await _create(client, group=_GROUP_ID, confirm=counting)

        assert posts_when_asked == [0], "the group notebook was created before the question"
        assert group_notebooks.call_count == 1

    async def test_a_site_create_asks_once_before_it_posts(
        self, client: GraphServiceClient, notebooks: respx.Route, site_notebooks: respx.Route
    ) -> None:
        posts_when_asked: list[int] = []

        async def counting(question: str, about: str) -> str | None:
            assert question
            assert about
            posts_when_asked.append(site_notebooks.call_count)
            return None

        _ = await _create(client, site=_SITE_ID, confirm=counting)

        assert posts_when_asked == [0], "the site notebook was created before the question"
        assert site_notebooks.call_count == 1
        assert notebooks.call_count == 0

    async def test_a_refusal_creates_nothing(
        self, client: GraphServiceClient, notebooks: respx.Route, group_notebooks: respx.Route
    ) -> None:
        with pytest.raises(ToolError, match="No notebook was created"):
            _ = await _create(client, group=_GROUP_ID, confirm=_refuses)

        assert group_notebooks.call_count == 0
        assert notebooks.call_count == 0

    async def test_a_refusal_for_a_site_creates_nothing(
        self, client: GraphServiceClient, notebooks: respx.Route, site_notebooks: respx.Route
    ) -> None:
        with pytest.raises(ToolError, match="No notebook was created"):
            _ = await _create(client, site=_SITE_ID, confirm=_refuses)

        assert site_notebooks.call_count == 0
        assert notebooks.call_count == 0

    @pytest.mark.usefixtures("group_notebooks")
    async def test_the_question_names_the_notebook_the_group_id_and_who_can_open_it(
        self, client: GraphServiceClient
    ) -> None:
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, name="Team Notes", group=_GROUP_ID, confirm=capturing)

        assert asked == [
            "Create the notebook 'Team Notes' in the Microsoft 365 group with the id "
            + f"{_GROUP_ID!r}? Every member of the group can open it."
        ]

    @pytest.mark.usefixtures("site_notebooks")
    async def test_the_question_names_the_notebook_the_site_id_and_who_can_open_it(
        self, client: GraphServiceClient
    ) -> None:
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, name="Site Notes", site=_SITE_ID, confirm=capturing)

        assert asked == [
            "Create the notebook 'Site Notes' in the SharePoint site with the id "
            + f"{_SITE_ID!r}? Other people with access to the site can open it."
        ]

    @pytest.mark.usefixtures("group_notebooks", "site_notebooks")
    async def test_about_binds_the_owner_kind_the_owner_and_the_name(
        self, client: GraphServiceClient
    ) -> None:
        bound: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert question
            bound.append(about)
            return None

        _ = await _create(client, name="Same", group=_GROUP_ID, confirm=capturing)
        _ = await _create(client, name="Same", group=_GROUP_ID, confirm=capturing)
        _ = await _create(client, name="Different", group=_GROUP_ID, confirm=capturing)
        _ = await _create(client, name="Same", site=_SITE_ID, confirm=capturing)

        assert bound[0] == bound[1]
        assert bound[2] != bound[0]
        assert bound[0] == write_state_for("create_notebook", "groups", _GROUP_ID, "Same")
        assert bound[3] == write_state_for("create_notebook", "sites", _SITE_ID, "Same")
        assert write_state_for("create_notebook", "groups", "another-group", "Same") != bound[0]
        assert write_state_for("create_notebook", "sites", _GROUP_ID, "Same") != bound[0]

    @pytest.mark.parametrize(
        "answer",
        [
            DeclinedElicitation(),
            CancelledElicitation(),
            AcceptedElicitation(data="do not create"),
            ToolError("the client refused the request"),
        ],
        ids=["declined", "cancelled", "another-answer", "client-error"],
    )
    async def test_every_gate_failure_creates_nothing(
        self, client: GraphServiceClient, group_notebooks: respx.Route, answer: object
    ) -> None:
        with pytest.raises(ToolError):
            _ = await create_notebook(
                client, name=_NAME, group=_GROUP_ID, confirm=a_person_agrees(_context(answer))
            )

        assert group_notebooks.call_count == 0

    async def test_a_client_that_cannot_ask_is_told_so_and_creates_nothing(
        self, client: GraphServiceClient, group_notebooks: respx.Route
    ) -> None:
        with pytest.raises(ToolError, match="does not support elicitation"):
            _ = await create_notebook(
                client,
                name=_NAME,
                group=_GROUP_ID,
                confirm=a_person_agrees(_context(MCPError(METHOD_NOT_FOUND, "Method not found"))),
            )

        assert group_notebooks.call_count == 0

    async def test_agreeing_creates_the_group_notebook(
        self, client: GraphServiceClient, group_notebooks: respx.Route
    ) -> None:
        answer = await create_notebook(
            client,
            name=_NAME,
            group=_GROUP_ID,
            confirm=a_person_agrees(_context(AcceptedElicitation(data="create"))),
        )

        assert isinstance(answer, creator.CreatedNotebook)
        assert group_notebooks.call_count == 1


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


async def _first_round(client: GraphServiceClient) -> tuple[str, str]:
    first = await create_notebook(
        client, name=_NAME, group=_GROUP_ID, confirm=a_person_agrees(_modern_context())
    )
    assert isinstance(first, InputRequiredResult)
    assert first.request_state is not None
    return next(iter(first.input_requests or {})), first.request_state


_AGREED = ElicitResult(action="accept", content={"value": "create"})


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_reaches_the_write(
        self, client: GraphServiceClient, group_notebooks: respx.Route
    ) -> None:
        answer = await create_notebook(
            client, name=_NAME, group=_GROUP_ID, confirm=a_person_agrees(_modern_context())
        )

        assert isinstance(answer, InputRequiredResult)
        assert answer.request_state == write_state_for(
            "create_notebook", "groups", _GROUP_ID, _NAME
        )
        assert group_notebooks.call_count == 0

    async def test_the_second_round_creates_what_was_agreed_to(
        self, client: GraphServiceClient, group_notebooks: respx.Route
    ) -> None:
        key, state = await _first_round(client)

        answer = await create_notebook(
            client,
            name=_NAME,
            group=_GROUP_ID,
            confirm=a_person_agrees(_modern_context(answers={key: _AGREED}, state=state)),
            answer_pending=True,
        )

        assert isinstance(answer, creator.CreatedNotebook)
        assert group_notebooks.call_count == 1

    async def test_a_second_round_for_a_different_name_creates_nothing(
        self, client: GraphServiceClient, group_notebooks: respx.Route
    ) -> None:
        key, state = await _first_round(client)

        with pytest.raises(ToolError, match="different request"):
            _ = await create_notebook(
                client,
                name="Another name",
                group=_GROUP_ID,
                confirm=a_person_agrees(_modern_context(answers={key: _AGREED}, state=state)),
                answer_pending=True,
            )

        assert group_notebooks.call_count == 0

    async def test_an_agreement_for_a_group_does_not_cover_a_create_without_one(
        self, client: GraphServiceClient, notebooks: respx.Route, group_notebooks: respx.Route
    ) -> None:
        key, state = await _first_round(client)

        with pytest.raises(ToolError, match="different request"):
            _ = await create_notebook(
                client,
                name=_NAME,
                confirm=a_person_agrees(_modern_context(answers={key: _AGREED}, state=state)),
                answer_pending=True,
            )

        assert notebooks.call_count == 0
        assert group_notebooks.call_count == 0

    async def test_an_agreement_for_a_group_does_not_cover_a_site_with_the_same_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        key, state = await _first_round(client)

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await create_notebook(
                client,
                name=_NAME,
                site=_GROUP_ID,
                confirm=a_person_agrees(_modern_context(answers={key: _AGREED}, state=state)),
                answer_pending=True,
            )

        assert len(graph.calls) == 0

    async def test_a_second_round_decline_creates_nothing(
        self, client: GraphServiceClient, group_notebooks: respx.Route
    ) -> None:
        key, state = await _first_round(client)

        with pytest.raises(ToolError, match="No notebook was created"):
            _ = await create_notebook(
                client,
                name=_NAME,
                group=_GROUP_ID,
                confirm=a_person_agrees(
                    _modern_context(answers={key: ElicitResult(action="decline")}, state=state)
                ),
                answer_pending=True,
            )

        assert group_notebooks.call_count == 0

    async def test_a_pending_decline_is_honored_without_a_group(
        self, client: GraphServiceClient, notebooks: respx.Route, group_notebooks: respx.Route
    ) -> None:
        key, state = await _first_round(client)

        with pytest.raises(ToolError, match="No notebook was created"):
            _ = await create_notebook(
                client,
                name=_NAME,
                confirm=a_person_agrees(
                    _modern_context(answers={key: ElicitResult(action="decline")}, state=state)
                ),
                answer_pending=True,
            )

        assert notebooks.call_count == 0
        assert group_notebooks.call_count == 0

    async def test_a_create_without_a_group_returns_no_question(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(return_value=httpx.Response(201, json=_notebook_payload()))

        answer = await create_notebook(
            client, name=_NAME, confirm=a_person_agrees(_modern_context())
        )

        assert isinstance(answer, creator.CreatedNotebook)
        assert notebooks.call_count == 1


class TestHowRegisterWiresTheQuestion:
    async def test_register_asks_for_a_group_and_not_without_one(
        self,
        transport: httpx.AsyncClient,
        client: GraphServiceClient,
        notebooks: respx.Route,
        group_notebooks: respx.Route,
    ) -> None:
        notebooks.mock(return_value=httpx.Response(201, json=_notebook_payload()))
        _parameters, tool = await _registered(transport)
        assert isinstance(tool, FunctionTool)

        asked = cast(
            "creator.CreatedNotebook | InputRequiredResult",
            await tool.fn(name=_NAME, group=_GROUP_ID, ctx=_modern_context(), client=client),
        )
        created = cast(
            "creator.CreatedNotebook | InputRequiredResult",
            await tool.fn(name=_NAME, ctx=_modern_context(), client=client),
        )

        assert isinstance(asked, InputRequiredResult)
        assert group_notebooks.call_count == 0
        assert isinstance(created, creator.CreatedNotebook)
        assert notebooks.call_count == 1

    async def test_register_passes_the_site_and_asks_for_it(
        self,
        transport: httpx.AsyncClient,
        client: GraphServiceClient,
        notebooks: respx.Route,
        site_notebooks: respx.Route,
    ) -> None:
        _parameters, tool = await _registered(transport)
        assert isinstance(tool, FunctionTool)

        asked = cast(
            "creator.CreatedNotebook | InputRequiredResult",
            await tool.fn(name=_NAME, site=_SITE_ID, ctx=_modern_context(), client=client),
        )

        assert isinstance(asked, InputRequiredResult)
        assert asked.request_state == write_state_for("create_notebook", "sites", _SITE_ID, _NAME)
        assert site_notebooks.call_count == 0
        assert notebooks.call_count == 0

    async def test_register_honors_a_pending_decline_without_a_group(
        self,
        transport: httpx.AsyncClient,
        client: GraphServiceClient,
        notebooks: respx.Route,
        group_notebooks: respx.Route,
    ) -> None:
        notebooks.mock(return_value=httpx.Response(201, json=_notebook_payload()))
        _parameters, tool = await _registered(transport)
        assert isinstance(tool, FunctionTool)
        key, state = await _first_round(client)

        with pytest.raises(ToolError, match="No notebook was created"):
            _ = cast(
                "creator.CreatedNotebook | InputRequiredResult",
                await tool.fn(
                    name=_NAME,
                    ctx=_modern_context(answers={key: ElicitResult(action="decline")}, state=state),
                    client=client,
                ),
            )

        assert notebooks.call_count == 0
        assert group_notebooks.call_count == 0


class TestHowItDeclaresItself:
    def test_the_permission_is_notes_create(self) -> None:
        assert creator.GRAPH_PERMISSIONS == ("Notes.Create",)

    def test_the_call_example_is_a_name(self) -> None:
        assert set(creator.GRAPH_CALL_EXAMPLE) == {"name"}

    async def test_the_call_example_is_accepted_by_the_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("dict[str, object]", parameters["properties"])
        assert set(creator.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_it_takes_a_name_and_an_optional_group_or_site_and_no_others(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("dict[str, object]", parameters["properties"])
        assert set(properties) == {"name", "group", "site"}
        assert parameters["required"] == ["name"]

    async def test_group_is_never_empty_and_says_where_to_take_its_id(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])

        group = properties["group"]
        assert cast("list[Mapping[str, object]]", group["anyOf"])[0]["minLength"] == 1
        described = cast("str", group["description"])
        assert "A team id is a group id." in described
        assert "Ask the user for it, or copy a team id from an earlier result." in described
        assert "teams_list_my_teams" not in described
        assert "Omit it to create the notebook in the user's own OneNote." in described
        assert 15 <= len(described.split()) <= 60

    async def test_site_is_never_empty_and_says_how_its_id_looks(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])

        site = properties["site"]
        assert cast("list[Mapping[str, object]]", site["anyOf"])[0]["minLength"] == 1
        described = cast("str", site["description"])
        assert described.startswith("The SharePoint site that owns the new notebook")
        assert "a host name and two ids, joined by commas, and not percent-encoded" in described
        assert "Pass at most one of `group` and `site`." in described
        assert "Omit both to create the notebook in the user's own OneNote." in described
        assert 15 <= len(described.split()) <= 60

    async def test_the_name_states_its_limits_in_60_words_or_fewer(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])

        described = cast("str", properties["name"]["description"])
        assert "unique in the OneNote of its owner" in described
        assert "at most 128 characters long" in described
        assert "Microsoft refuses a bad name and creates nothing." in described
        assert "Read it from the answer" not in described
        assert 15 <= len(described.split()) <= 60

    def test_the_stored_name_has_its_home_on_the_answer_field(self) -> None:
        stored = creator.CreatedNotebook.model_fields["name"].description or ""

        assert "What Microsoft stored, read from its response" in stored
        assert "not from the `name` argument" in stored

    @pytest.mark.parametrize("word", ["client", "ctx", "context", "token", "graph"])
    async def test_no_wiring_of_this_server_is_published_as_an_argument(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("dict[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_it_announces_itself_as_an_additive_write(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)
        assert isinstance(tool, FunctionTool)

        annotations = tool.annotations
        assert annotations is not None, (
            "a tool with no annotations joins the write surface by omission"
        )
        assert annotations.read_only_hint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_ADDITIVE["idempotentHint"]

    async def test_the_description_says_it_never_asks_without_an_owner_and_asks_with_one(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        flat = " ".join(description.split())
        assert (
            "Without `group` or `site`, a new notebook belongs to the user alone and starts "
            + "unshared, so this tool never asks anybody to agree."
        ) in flat
        assert "never asks" in description.casefold()
        assert "unshared" in description.casefold()
        assert (
            "This tool asks the user to agree before it creates a notebook in a group or a site. "
            + "Other people can open that notebook."
        ) in flat
        assert "The question shows only the id of the group or the site." in flat
        assert (
            "If you know the name of that group or site, tell it to the user before you call."
        ) in flat

    async def test_the_description_has_a_lead_and_notes_in_the_house_shape(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        lead, separator, notes = description.partition("\n\nNotes:\n")
        bullets = [line for line in notes.splitlines() if line.startswith("- ")]
        assert separator, "the description has no Notes section"
        assert 45 <= len(description.split()) <= 210
        assert 1 <= len(bullets) <= 4
        assert "`group`" in lead
        assert "`site`" in lead
        assert "SharePoint site" in lead
        assert "onenote_copy_notebook" in lead

    async def test_the_retry_advice_looks_under_the_same_group_or_site(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = " ".join((tool.description or "").split())
        assert "onenote_list_notebooks with the same `group` or `site`" in description

    def test_the_answer_scopes_its_always_claims_to_a_create_without_an_owner(self) -> None:
        fields = creator.CreatedNotebook.model_fields

        assert "Without `group` or `site`, a brand-new notebook is always unshared" in (
            fields["is_shared"].description or ""
        )
        assert 'Without `group` or `site`, a notebook this call created is always "Owner"' in (
            fields["user_role"].description or ""
        )
        assert "Without `group` or `site`, this is possible only when the user had no notebook" in (
            fields["is_default"].description or ""
        )
        assert (
            "A handle from a group or site notebook starts with onenote:///groups/{group}/ "
            + "or onenote:///sites/{site}/ instead."
            in (fields["uri"].description or "")
        )

    async def test_the_name_description_lists_the_forbidden_characters(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        name = cast("Mapping[str, object]", properties["name"])
        description = cast("str", name["description"])
        for character in "?*/:<>|'\"":
            assert character in description, f"{character!r} missing from the description"

    async def test_the_description_states_the_duplicate_name_failure_as_a_fact(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "Microsoft refuses a duplicate name, and the same name fails again" in description
        assert "confirmed on a test tenant" not in description
        assert "most often comes back as" not in description
        assert "bad request" not in description
