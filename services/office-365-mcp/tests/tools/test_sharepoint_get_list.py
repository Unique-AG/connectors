import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.shared.handles import DriveFolderHandle, ListHandle
from office_365_mcp.tools.sharepoint_get_list import get_list

_SITE_ID = (
    "contoso.sharepoint.invalid,00000000-0000-4000-8000-00000000000a,"
    + "11111111-aaaa-bbbb-cccc-222222222222"
)
_LIST_ID = "0b1c2d3e-0000-4000-8000-00000000000a"
_LIST_URI = ListHandle(_SITE_ID, _LIST_ID).uri


async def test_it_maps_each_column_facet_to_a_type(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    graph.get(f"/sites/{_SITE_ID}/lists/{_LIST_ID}/columns").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "name": "Title",
                        "displayName": "Title",
                        "required": True,
                        "readOnly": False,
                        "indexed": False,
                        "text": {"maxLength": 255},
                    },
                    {
                        "name": "Status",
                        "displayName": "Status",
                        "indexed": True,
                        "choice": {"choices": ["Open", "Closed"]},
                    },
                    {
                        "name": "_ModerationComments",
                        "displayName": "Approver Comments",
                        "hidden": True,
                        "readOnly": True,
                    },
                ]
            },
        )
    )

    result = await get_list(client, list_uri=_LIST_URI)

    title, status, hidden = result.columns
    assert (title.name, title.display_name, title.type, title.choices) == (
        "Title",
        "Title",
        "text",
        None,
    )
    assert (title.required, title.read_only, title.indexed) == (True, False, False)
    assert (status.type, status.choices, status.indexed) == ("choice", ["Open", "Closed"], True)
    assert status.required is None
    assert (hidden.name, hidden.type, hidden.read_only) == ("_ModerationComments", "other", True)


@pytest.mark.parametrize("value", ["Tasks", DriveFolderHandle("b!drive", "root").uri])
async def test_a_value_that_is_not_a_list_handle_makes_no_graph_call(
    client: GraphServiceClient, graph: respx.MockRouter, value: str
) -> None:
    with pytest.raises(ToolError):
        _ = await get_list(client, list_uri=value)

    assert not graph.calls
