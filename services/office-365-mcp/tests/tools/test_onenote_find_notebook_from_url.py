import json
from collections.abc import Mapping
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    OnenoteOwner,
    OnenotePageHandle,
    OnenoteSectionGroupHandle,
    OnenoteSectionHandle,
)
from office_365_mcp.shared.seam import READ_ONLY, Advised
from office_365_mcp.tools import onenote_find_notebook_from_url as finder

NOTEBOOK_ID = "1-SYNTHETICNOTEBOOK0000!0001"
GROUP_ID = "2b7c9d10-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
OTHER_GROUP_ID = "7e8f9a0b-1c2d-4e3f-8a4b-5c6d7e8f9a0b"
SITE_ID = (
    "contoso.sharepoint.invalid,0d1e2f3a-0000-4000-8000-000000000001,"
    + "4b5c6d7e-0000-4000-8000-000000000002"
)
USER_ID = "5a6b7c8d-9e0f-4a1b-8c2d-3e4f5a6b7c8d"

_WEB_URL = "https://onenote.example.invalid/notebooks/team-notebook"
_CLIENT_URL = "onenote:https://onenote.example.invalid/notebooks/team-notebook"

_PATH = "/me/onenote/notebooks/getNotebookFromWebUrl"
_GROUP_PATH = f"/groups/{GROUP_ID}/onenote/notebooks/getNotebookFromWebUrl"
_SITE_PATH = f"/sites/{SITE_ID}/onenote/notebooks/getNotebookFromWebUrl"

_GRAPH = "https://graph.microsoft.com/v1.0"


def _notebook_payload(
    *,
    notebook_id: str | None = NOTEBOOK_ID,
    name: str | None = "Team Notebook",
    is_default: bool | None = True,
    is_shared: bool | None = False,
    user_role: str | None = "Owner",
    web_url: str | None = _WEB_URL,
    client_url: str | None = _CLIENT_URL,
    created: str | None = "2026-01-05T09:30:00Z",
    modified: str | None = "2026-03-12T14:45:00Z",
    links: bool = True,
    self_url: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": notebook_id,
        "name": name,
        "isDefault": is_default,
        "isShared": is_shared,
        "userRole": user_role,
        "createdTime": created,
        "lastModifiedTime": modified,
    }
    if self_url is not None:
        payload["self"] = self_url
    if links:
        payload["links"] = {
            "oneNoteWebUrl": {"href": web_url} if web_url is not None else None,
            "oneNoteClientUrl": {"href": client_url} if client_url is not None else None,
        }
    else:
        payload["links"] = None
    return payload


@pytest.fixture
def found(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_PATH).mock(return_value=httpx.Response(200, json=_notebook_payload()))


@pytest.fixture
def found_for_a_group(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_GROUP_PATH).mock(return_value=httpx.Response(200, json=_notebook_payload()))


@pytest.fixture
def found_for_a_site(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_SITE_PATH).mock(return_value=httpx.Response(200, json=_notebook_payload()))


async def _find(
    client: GraphServiceClient,
    *,
    web_url: str = _WEB_URL,
    group: str | None = None,
    site: str | None = None,
) -> finder.FoundNotebook:
    return await finder.find_notebook_from_url(client, web_url=web_url, group=group, site=site)


class TestWhatItAsks:
    async def test_it_sends_the_web_url_verbatim_in_the_body(
        self, client: GraphServiceClient, found: respx.Route
    ) -> None:
        _ = await _find(client)

        sent = cast("dict[str, object]", json.loads(found.calls.last.request.content))
        assert sent == {"webUrl": _WEB_URL}

    async def test_a_very_long_web_url_reaches_graph(
        self, client: GraphServiceClient, found: respx.Route
    ) -> None:
        long_url = f"{_WEB_URL}?{'a' * 5000}"

        _ = await _find(client, web_url=long_url)

        sent = cast("dict[str, object]", json.loads(found.calls.last.request.content))
        assert sent == {"webUrl": long_url}

    async def test_the_request_carries_no_query_parameters(
        self, client: GraphServiceClient, found: respx.Route
    ) -> None:
        _ = await _find(client)

        assert found.calls.last.request.url.params == httpx.QueryParams()

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_declined_call_is_retried_by_default(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post(_PATH).mock(
            side_effect=[httpx.Response(503), httpx.Response(200, json=_notebook_payload())]
        )

        _ = await _find(client)

        assert route.call_count == 2, (
            "getNotebookFromWebUrl is a read spelled as a POST, so the SDK's default retry runs"
        )


class TestTheGroupRoute:
    async def test_a_group_asks_that_groups_route_and_never_the_users(
        self, client: GraphServiceClient, found: respx.Route, found_for_a_group: respx.Route
    ) -> None:
        _ = await _find(client, group=GROUP_ID)

        assert found_for_a_group.call_count == 1
        assert found.call_count == 0

    async def test_no_group_asks_the_users_route_and_never_a_groups(
        self, client: GraphServiceClient, found: respx.Route, found_for_a_group: respx.Route
    ) -> None:
        _ = await _find(client)

        assert found.call_count == 1
        assert found_for_a_group.call_count == 0

    async def test_the_group_route_sends_the_same_body_and_no_query_parameters(
        self, client: GraphServiceClient, found_for_a_group: respx.Route
    ) -> None:
        _ = await _find(client, group=GROUP_ID)

        request = found_for_a_group.calls.last.request
        assert cast("dict[str, object]", json.loads(request.content)) == {"webUrl": _WEB_URL}
        assert request.url.params == httpx.QueryParams()
        assert request.headers["accept"] == "application/json"

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_declined_group_call_is_retried_by_default(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post(_GROUP_PATH).mock(
            side_effect=[httpx.Response(503), httpx.Response(200, json=_notebook_payload())]
        )

        _ = await _find(client, group=GROUP_ID)

        assert route.call_count == 2

    @pytest.mark.usefixtures("found_for_a_group")
    async def test_the_minted_handle_carries_the_group(self, client: GraphServiceClient) -> None:
        answer = await _find(client, group=GROUP_ID)

        assert (
            answer.uri
            == OnenoteNotebookHandle(NOTEBOOK_ID, owner=OnenoteOwner("groups", GROUP_ID)).uri
        )
        assert answer.uri.startswith(f"onenote:///groups/{GROUP_ID}/notebooks/")

    @pytest.mark.usefixtures("found")
    async def test_the_minted_handle_of_a_call_with_no_group_names_no_group(
        self, client: GraphServiceClient
    ) -> None:
        answer = await _find(client)

        assert answer.uri == OnenoteNotebookHandle(NOTEBOOK_ID).uri
        assert "/groups/" not in answer.uri

    @pytest.mark.usefixtures("found_for_a_group")
    async def test_the_rest_of_the_answer_is_mapped_as_for_the_user(
        self, client: GraphServiceClient
    ) -> None:
        answer = await _find(client, group=GROUP_ID)

        assert answer.name == "Team Notebook"
        assert answer.web_url == _WEB_URL
        assert answer.client_url == _CLIENT_URL

    async def test_a_404_on_the_group_route_is_a_graph_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_GROUP_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _find(client, group=GROUP_ID)

    def test_the_not_found_advice_names_the_group_and_the_site_and_keeps_the_retry_warning(
        self,
    ) -> None:
        assert "If this call named a `group` or a `site`" in finder.GRAPH_NOT_FOUND
        assert "A call with another one, or with none, can still work." in finder.GRAPH_NOT_FOUND
        assert "fails again" in finder.GRAPH_NOT_FOUND


class TestTheSiteRoute:
    async def test_a_site_asks_that_sites_route_and_never_the_users(
        self, client: GraphServiceClient, found: respx.Route, found_for_a_site: respx.Route
    ) -> None:
        _ = await _find(client, site=SITE_ID)

        assert found_for_a_site.call_count == 1
        assert found.call_count == 0

    async def test_the_site_route_sends_the_same_body_and_no_query_parameters(
        self, client: GraphServiceClient, found_for_a_site: respx.Route
    ) -> None:
        _ = await _find(client, site=SITE_ID)

        request = found_for_a_site.calls.last.request
        assert cast("dict[str, object]", json.loads(request.content)) == {"webUrl": _WEB_URL}
        assert request.url.params == httpx.QueryParams()

    @pytest.mark.usefixtures("found_for_a_site")
    async def test_the_minted_handle_carries_the_site(self, client: GraphServiceClient) -> None:
        answer = await _find(client, site=SITE_ID)

        assert (
            answer.uri
            == OnenoteNotebookHandle(NOTEBOOK_ID, owner=OnenoteOwner("sites", SITE_ID)).uri
        )
        assert answer.uri.startswith("onenote:///sites/")

    async def test_a_group_and_a_site_together_are_refused_before_any_graph_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await _find(client, group=GROUP_ID, site=SITE_ID)

        assert str(refused.value) == (
            "onenote_find_notebook_from_url takes at most one of `group` and `site`. A notebook "
            + "belongs to one group or one site, never to both. The same combination fails "
            + "again, so do not retry it as it is."
        )
        assert len(graph.calls) == 0


class TestTheOwnerMicrosoftNames:
    async def test_a_self_link_in_a_group_gives_a_group_handle_with_no_group_named(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_PATH).mock(
            return_value=httpx.Response(
                200,
                json=_notebook_payload(
                    self_url=f"{_GRAPH}/groups/{GROUP_ID}/onenote/notebooks/{NOTEBOOK_ID}"
                ),
            )
        )

        answer = await _find(client)

        assert (
            answer.uri
            == OnenoteNotebookHandle(NOTEBOOK_ID, owner=OnenoteOwner("groups", GROUP_ID)).uri
        )
        assert answer.uri.startswith(f"onenote:///groups/{GROUP_ID}/notebooks/")

    async def test_a_self_link_on_a_site_gives_a_site_handle_with_no_site_named(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_PATH).mock(
            return_value=httpx.Response(
                200,
                json=_notebook_payload(
                    self_url=f"{_GRAPH}/sites/{SITE_ID}/onenote/notebooks/{NOTEBOOK_ID}"
                ),
            )
        )

        answer = await _find(client)

        assert (
            answer.uri
            == OnenoteNotebookHandle(NOTEBOOK_ID, owner=OnenoteOwner("sites", SITE_ID)).uri
        )

    @pytest.mark.parametrize(
        "self_url",
        [f"{_GRAPH}/users/{USER_ID}/onenote/notebooks/{NOTEBOOK_ID}", None],
        ids=["a-user-self-link", "no-self-link"],
    )
    async def test_a_self_link_with_no_group_or_site_gives_a_handle_with_no_owner(
        self, client: GraphServiceClient, graph: respx.MockRouter, self_url: str | None
    ) -> None:
        _ = graph.post(_PATH).mock(
            return_value=httpx.Response(200, json=_notebook_payload(self_url=self_url))
        )

        answer = await _find(client)

        assert answer.uri == OnenoteNotebookHandle(NOTEBOOK_ID).uri

    async def test_a_named_group_wins_over_a_self_link_that_names_another_group(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_GROUP_PATH).mock(
            return_value=httpx.Response(
                200,
                json=_notebook_payload(
                    self_url=f"{_GRAPH}/groups/{OTHER_GROUP_ID}/onenote/notebooks/{NOTEBOOK_ID}"
                ),
            )
        )

        answer = await _find(client, group=GROUP_ID)

        assert (
            answer.uri
            == OnenoteNotebookHandle(NOTEBOOK_ID, owner=OnenoteOwner("groups", GROUP_ID)).uri
        )


class TestWhatItAnswers:
    async def test_the_notebook_is_mapped_from_graph(
        self, client: GraphServiceClient, found: respx.Route
    ) -> None:
        answer = await _find(client)

        assert answer.uri == OnenoteNotebookHandle(NOTEBOOK_ID).uri
        assert answer.name == "Team Notebook"
        assert answer.is_default is True
        assert answer.is_shared is False
        assert answer.user_role == "Owner"
        assert answer.web_url == _WEB_URL
        assert answer.client_url == _CLIENT_URL
        assert answer.created_at is not None
        assert answer.last_modified_at is not None
        assert found.call_count == 1

    async def test_no_links_at_all_answers_null_addresses(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_PATH).mock(
            return_value=httpx.Response(200, json=_notebook_payload(links=False))
        )

        answer = await _find(client)

        assert answer.web_url is None
        assert answer.client_url is None

    async def test_no_user_role_answers_null(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_PATH).mock(
            return_value=httpx.Response(200, json=_notebook_payload(user_role=None))
        )

        answer = await _find(client)

        assert answer.user_role is None


class TestGraphFailures:
    async def test_a_404_is_a_graph_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _find(client)

    async def test_a_403_is_a_graph_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "Forbidden"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _find(client)

    @pytest.mark.parametrize(
        ("owner", "route"),
        [({"group": GROUP_ID}, _GROUP_PATH), ({"site": SITE_ID}, _SITE_PATH)],
        ids=["group", "site"],
    )
    async def test_a_refusal_for_a_named_owner_arrives_as_advice_with_the_diagnostics(
        self, client: GraphServiceClient, graph: respx.MockRouter, owner: dict[str, str], route: str
    ) -> None:
        _ = graph.post(route).mock(
            return_value=httpx.Response(
                403,
                headers={"request-id": "req-7"},
                json={"error": {"code": "accessDenied", "message": "denied"}},
            )
        )

        with pytest.raises(Advised) as refused:
            _ = await _find(client, **owner)

        assert str(refused.value) == (
            f"{finder._OWNER_REFUSED} "  # pyright: ignore[reportPrivateUsage]
            + "(HTTP 403, Graph error code accessDenied, Graph request id req-7)"
        )
        assert isinstance(refused.value.__cause__, GraphForbidden)

    def test_the_advice_for_a_refused_owner_is_the_canonical_text(self) -> None:
        assert finder._OWNER_REFUSED == (  # pyright: ignore[reportPrivateUsage]
            "Microsoft 365 refused this request for the `group` or the `site` that this call "
            + "named. Most likely, the signed-in user is not a member of that group or site, or "
            + "the id is wrong. Ask the user for the correct id, or ask them to get access. If "
            + "this tool works without `group` and `site`, the permissions of this connector are "
            + "not the problem. If it fails without them too, ask a Microsoft 365 administrator "
            + "to grant the delegated permission Notes.Read. This same call fails again, so do "
            + "not retry it."
        )


class TestWhatItRefuses:
    async def test_a_notebook_handle_is_refused_before_any_graph_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="needs no resolving"):
            _ = await _find(client, web_url=OnenoteNotebookHandle("1-ABC").uri)

        assert len(graph.calls) == 0

    async def test_a_group_notebook_handle_is_refused_before_any_graph_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        handle = OnenoteNotebookHandle("1-ABC", owner=OnenoteOwner("groups", GROUP_ID)).uri

        with pytest.raises(ToolError, match="needs no resolving"):
            _ = await _find(client, web_url=handle, group=GROUP_ID)

        assert len(graph.calls) == 0

    @pytest.mark.parametrize(
        "value",
        [
            OnenoteSectionGroupHandle("1-ABC").uri,
            OnenoteSectionHandle("1-ABC").uri,
            OnenotePageHandle("1-ABC!0").uri,
            OnenoteSectionGroupHandle("1-ABC", owner=OnenoteOwner("groups", GROUP_ID)).uri,
            OnenoteSectionHandle("1-ABC", owner=OnenoteOwner("groups", GROUP_ID)).uri,
            OnenotePageHandle("1-ABC!0", owner=OnenoteOwner("groups", GROUP_ID)).uri,
        ],
    )
    async def test_a_page_section_or_group_handle_is_refused_before_any_graph_call(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError, match="does not resolve it"):
            _ = await _find(client, web_url=value)

        assert len(graph.calls) == 0


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    finder.register(mcp, transport)
    tool = await mcp.get_tool(finder.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestHowItDeclaresItself:
    def test_the_permission_is_notes_read(self) -> None:
        assert finder.GRAPH_PERMISSIONS == ("Notes.Read",)

    def test_the_call_example_is_a_web_url(self) -> None:
        assert set(finder.GRAPH_CALL_EXAMPLE) == {"web_url"}

    async def test_the_call_example_is_accepted_by_the_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(finder.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_it_takes_the_web_address_the_group_and_the_site_and_no_others(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"web_url", "group", "site"}

    async def test_only_the_web_address_is_required(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)
        assert parameters["required"] == ["web_url"]

    async def test_the_group_argument_says_whose_notebook_the_address_opens(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])
        described = cast("str", properties["group"]["description"])
        assert described.startswith(
            "The Microsoft 365 group or team whose notebook this address opens"
        )
        assert "A team id is a group id." in described
        assert "Take it from teams_list_my_teams, or ask the user for it." in described
        assert 15 <= len(described.split()) <= 60

    async def test_the_site_argument_says_how_a_site_id_is_spelled_and_where_it_comes_from(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])
        described = cast("str", properties["site"]["description"])
        assert described.startswith("The SharePoint site whose notebook this address opens")
        assert "as its Graph site id" in described
        assert "a host name and two ids, joined by commas, and not percent-encoded" in described
        assert "Ask the user for it." in described
        assert "Pass at most one of `group` and `site`." in described
        assert 15 <= len(described.split()) <= 60

    async def test_the_description_has_a_lead_with_the_sibling_and_notes_with_the_owner_bullets(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        lead, separator, notes = description.partition("\n\nNotes:\n")
        bullets = [line for line in notes.splitlines() if line.startswith("- ")]
        assert separator, "the description has no Notes section"
        assert 45 <= len(description.split()) <= 210
        assert 1 <= len(bullets) <= 3
        assert "onenote_list_recent_notebooks" in lead
        assert any("Pass `group` or `site`" in bullet for bullet in bullets)
        assert any("only when Microsoft names it in its answer" in bullet for bullet in bullets)
        assert any(
            "answers not found, call this tool again with `group` or `site`" in bullet
            for bullet in bullets
        )

    def test_the_answer_handle_says_how_a_group_or_site_notebook_handle_starts(self) -> None:
        described = finder.FoundNotebook.model_fields["uri"].description or ""
        assert (
            "starts with onenote:///groups/{group}/ " + "or onenote:///sites/{site}/ instead"
            in described
        )

    @pytest.mark.parametrize("word", ["client", "ctx", "context", "token", "graph"])
    async def test_no_wiring_of_this_server_is_published_as_an_argument(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_it_announces_itself_as_read_only(self, transport: httpx.AsyncClient) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None, "a tool with no annotations joins the write surface"
        assert annotations.read_only_hint is READ_ONLY["readOnlyHint"]
