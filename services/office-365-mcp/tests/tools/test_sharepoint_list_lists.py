import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.shared.handles import ListHandle, list_handle
from office_365_mcp.tools.sharepoint_list_lists import list_lists

_HOST = "contoso.sharepoint.invalid"
_SITE_ID = (
    f"{_HOST},00000000-0000-4000-8000-00000000000a,"
    + "11111111-aaaa-bbbb-cccc-222222222222"
)
_SITE = {"id": _SITE_ID, "webUrl": f"https://{_HOST}/sites/Finance"}
_LISTS_ROUTE = f"/sites/{_SITE_ID}/lists"


def _list(list_id: str, title: str, *, template: str, hidden: bool = False) -> dict[str, object]:
    return {
        "id": list_id,
        "displayName": title,
        "description": f"{title} description",
        "webUrl": f"https://{_HOST}/sites/Finance/Lists/{title}",
        "list": {"template": template, "hidden": hidden},
    }


async def test_it_returns_visible_lists_and_leaves_out_hidden_lists_and_libraries(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    resolve = graph.get(f"/sites/{_HOST}:/sites/Finance").mock(
        return_value=httpx.Response(200, json=_SITE)
    )
    graph.get(_LISTS_ROUTE).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    _list("L-HIDDEN", "Workflow", template="genericList", hidden=True),
                    _list("L-DOCS", "Documents", template="documentLibrary"),
                    _list("L-MINE", "Personal", template="mySiteDocumentLibrary"),
                    _list("L-TASKS", "Tasks", template="genericList"),
                    _list("L-ISSUES", "Issues", template="issueTracking"),
                    {**_list("", "Nameless", template="genericList"), "id": None},
                ]
            },
        )
    )

    result = await list_lists(client, site=f"https://{_HOST}/sites/Finance", limit=25)

    assert resolve.called
    assert [row.display_name for row in result.lists] == ["Tasks", "Issues"]
    assert [list_handle(row.uri) for row in result.lists] == [
        ListHandle(_SITE_ID, "L-TASKS"),
        ListHandle(_SITE_ID, "L-ISSUES"),
    ]
    assert result.lists[0].description == "Tasks description"
    assert result.lists[0].web_url == f"https://{_HOST}/sites/Finance/Lists/Tasks"
    assert result.capped is False


async def test_a_site_url_with_no_path_resolves_the_root_site(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    resolve = graph.get(f"/sites/{_HOST}").mock(return_value=httpx.Response(200, json=_SITE))
    graph.get(_LISTS_ROUTE).mock(return_value=httpx.Response(200, json={"value": []}))

    result = await list_lists(client, site=f"https://{_HOST}", limit=25)

    assert resolve.called
    assert result.lists == []


@pytest.mark.parametrize(
    "site",
    ["Finance", "contoso.sharepoint.invalid/sites/Finance", ListHandle(_SITE_ID, "L-TASKS").uri],
)
async def test_a_value_that_is_not_a_site_url_makes_no_graph_call(
    client: GraphServiceClient, graph: respx.MockRouter, site: str
) -> None:
    with pytest.raises(ToolError):
        _ = await list_lists(client, site=site, limit=25)

    assert not graph.calls
