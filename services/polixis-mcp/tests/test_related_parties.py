import json

import httpx2

from polixis_mcp import contexts
from tests.tool_calls import call_tool
from tests.tool_calls import McpClient


async def test_get_related_parties_returns_each_party_with_its_relations(
    mcp_client: McpClient,
) -> None:
    page = await call_tool(
        mcp_client,
        "get_related_parties",
        {"pid": "O00000000000000000000000000000100"},
        returns=contexts.RelatedPartiesPage,
    )

    assert page.total_parties == 26
    assert [party.model_dump() for party in page.parties] == [
        {
            "pid": "P00000000000000000000000000000200",
            "name": "Anna Example",
            "entity_type": "PERSON",
            "countries": ["ch", "li"],
            "flags": ["PEP"],
            "alerts": ["Politically exposed person"],
            "relations": [
                {
                    "relation_type": "shareholding_ownership",
                    "title": "shareholder",
                    "share_percent": 60.0,
                    "former": False,
                    "start_date": "2019-05",
                    "end_date": None,
                    "information_date": "2026-10-01",
                    "source": "Example Commercial Register",
                }
            ],
        },
        {
            "pid": None,
            "name": "Pat Signatory",
            "entity_type": "PERSON",
            "countries": [],
            "flags": [],
            "alerts": [],
            "relations": [
                {
                    "relation_type": "signature",
                    "title": "signatory",
                    "share_percent": None,
                    "former": False,
                    "start_date": None,
                    "end_date": None,
                    "information_date": None,
                    "source": None,
                }
            ],
        },
    ]


async def test_get_related_parties_asks_for_every_category_on_the_first_page(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    await mcp_client.call_tool(
        "get_related_parties", {"pid": "O00000000000000000000000000000100", "page_size": 40}
    )

    request = upstream_requests[-1]
    assert dict(request.url.params) == {"page": "0", "size": "40"}
    assert json.loads(request.content) == {
        "id": "O00000000000000000000000000000100",
        "category": [
            "executive",
            "executiveSenior",
            "board",
            "political",
            "signature",
            "thirdParty",
            "membership",
            "shareholdingInformation",
            "ownershipInOtherEntities",
        ],
    }


async def test_get_related_parties_cursor_asks_polixis_for_its_next_page(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    first = await call_tool(
        mcp_client,
        "get_related_parties",
        {"pid": "O00000000000000000000000000000100", "categories": ["executive"], "page_size": 10},
        returns=contexts.RelatedPartiesPage,
    )

    await mcp_client.call_tool("get_related_parties", {"cursor": first.next_cursor})

    request = upstream_requests[-1]
    assert dict(request.url.params) == {"page": "1", "size": "10"}
    assert json.loads(request.content) == {
        "id": "O00000000000000000000000000000100",
        "category": ["executive"],
    }
