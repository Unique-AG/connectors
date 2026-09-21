import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.tools import onenote_list_recent_notebooks as lister

from .conftest import GRAPH_V1

_TRUE_PATH = "/me/onenote/notebooks/getRecentNotebooks(includePersonalNotebooks=true)"
_FALSE_PATH = "/me/onenote/notebooks/getRecentNotebooks(includePersonalNotebooks=false)"

_WEB_URL = "https://onenote.example.invalid/notebooks/team-notebook"
_CLIENT_URL = "onenote:https://onenote.example.invalid/notebooks/team-notebook"


def _recent(
    *,
    name: str | None = "Team Notebook",
    accessed: str | None = "2026-03-01T09:00:00Z",
    web_url: str | None = _WEB_URL,
    client_url: str | None = _CLIENT_URL,
    source_service: str | None = "OneDriveForBusiness",
    links: bool = True,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "displayName": name,
        "lastAccessedTime": accessed,
        "sourceService": source_service,
    }
    if links:
        payload["links"] = {
            "oneNoteWebUrl": {"href": web_url} if web_url is not None else None,
            "oneNoteClientUrl": {"href": client_url} if client_url is not None else None,
        }
    else:
        payload["links"] = None
    return payload


@pytest.fixture
def recent(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_TRUE_PATH).mock(return_value=httpx.Response(200, json={"value": [_recent()]}))


async def _list(
    client: GraphServiceClient, *, include_personal_notebooks: bool = True
) -> lister.RecentNotebooks:
    return await lister.list_recent_notebooks(
        client, include_personal_notebooks=include_personal_notebooks
    )


class TestWhatItAsks:
    async def test_the_default_includes_personal_notebooks(
        self, client: GraphServiceClient, recent: respx.Route
    ) -> None:
        _ = await _list(client)

        assert recent.call_count == 1

    async def test_false_asks_the_false_variant_of_the_function(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(_FALSE_PATH).mock(
            return_value=httpx.Response(200, json={"value": [_recent()]})
        )

        _ = await _list(client, include_personal_notebooks=False)

        assert route.call_count == 1


class TestWhatItAnswers:
    @pytest.mark.usefixtures("recent")
    async def test_a_row_is_mapped_from_graph(self, client: GraphServiceClient) -> None:
        answer = await _list(client)

        assert len(answer.notebooks) == 1
        row = answer.notebooks[0]
        assert row.name == "Team Notebook"
        assert row.last_accessed_at is not None
        assert row.web_url == _WEB_URL
        assert row.client_url == _CLIENT_URL
        assert row.source_service == "OneDriveForBusiness"
        assert answer.capped is False

    async def test_no_links_at_all_answers_null_addresses(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_TRUE_PATH).mock(
            return_value=httpx.Response(200, json={"value": [_recent(links=False)]})
        )

        answer = await _list(client)

        assert answer.notebooks[0].web_url is None
        assert answer.notebooks[0].client_url is None

    async def test_no_source_service_answers_null(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_TRUE_PATH).mock(
            return_value=httpx.Response(200, json={"value": [_recent(source_service=None)]})
        )

        answer = await _list(client)

        assert answer.notebooks[0].source_service is None

    async def test_an_empty_collection_answers_an_empty_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_TRUE_PATH).mock(return_value=httpx.Response(200, json={"value": []}))

        answer = await _list(client)

        assert answer.notebooks == []
        assert answer.capped is False


class TestTheCap:
    async def test_the_notebooks_are_followed_across_a_next_link(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_TRUE_PATH, params={"$skiptoken": "second"}).mock(
            return_value=httpx.Response(200, json={"value": [_recent(name="Second")]})
        )
        graph.get(_TRUE_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [_recent(name="First")],
                    "@odata.nextLink": f"{GRAPH_V1}{_TRUE_PATH}?$skiptoken=second",
                },
            )
        )

        answer = await _list(client)

        assert [row.name for row in answer.notebooks] == ["First", "Second"]
        assert answer.capped is False

    async def test_more_than_the_cap_in_one_page_says_capped(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        items = [_recent(name=f"Notebook {i}") for i in range(lister.MAX_RECENT + 1)]
        _ = graph.get(_TRUE_PATH).mock(return_value=httpx.Response(200, json={"value": items}))

        answer = await _list(client)

        assert len(answer.notebooks) == lister.MAX_RECENT
        assert answer.capped is True


class TestGraphFailures:
    async def test_a_403_is_a_graph_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_TRUE_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "Forbidden"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _list(client)
