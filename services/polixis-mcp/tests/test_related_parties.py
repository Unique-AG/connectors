from collections.abc import Mapping
import json

import httpx2
import pytest

from polixis_mcp import contexts
from tests import polixis_responses
from tests.tool_calls import call_tool
from tests.tool_calls import McpClient

ORGANIZATION = "O00000000000000000000000000000100"


async def test_get_related_parties_merges_a_party_every_publisher_reports(
    mcp_client: McpClient,
) -> None:
    page = await call_tool(
        mcp_client,
        "get_related_parties",
        {"pid": ORGANIZATION},
        returns=contexts.RelatedPartiesPage,
    )

    assert page.total_parties is None
    assert page.relations_by_source == {"Example Commercial Register": 3, "Example PEP List": 41}
    assert [party.model_dump() for party in page.parties] == [
        {
            "pid": "P00000000000000000000000000000200",
            "name": "Anna Example",
            "entity_type": "PERSON",
            "countries": ["ch", "li", "de"],
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
                },
                {
                    "relation_type": "board",
                    "title": "board member",
                    "share_percent": None,
                    "former": False,
                    "start_date": None,
                    "end_date": None,
                    "information_date": None,
                    "source": "Example PEP List",
                },
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
                    "former": True,
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
    await mcp_client.call_tool("get_related_parties", {"pid": ORGANIZATION})

    request = upstream_requests[-1]
    assert dict(request.url.params) == {"page": "0", "size": "40"}
    assert json.loads(request.content) == {
        "id": ORGANIZATION,
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


async def test_get_related_parties_reads_the_next_page_from_the_cache(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    first = await call_tool(
        mcp_client,
        "get_related_parties",
        {"pid": ORGANIZATION, "page_size": 1},
        returns=contexts.RelatedPartiesPage,
    )
    sent = len(upstream_requests)

    second = await call_tool(
        mcp_client,
        "get_related_parties",
        {"cursor": first.next_cursor},
        returns=contexts.RelatedPartiesPage,
    )

    assert [party.name for party in [*first.parties, *second.parties]] == [
        "Anna Example",
        "Pat Signatory",
    ]
    assert len(upstream_requests) == sent


async def test_get_related_parties_asks_polixis_for_its_next_page_after_the_last_party(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    first = await call_tool(
        mcp_client,
        "get_related_parties",
        {"pid": ORGANIZATION, "categories": ["executive"]},
        returns=contexts.RelatedPartiesPage,
    )

    await mcp_client.call_tool("get_related_parties", {"cursor": first.next_cursor})

    request = upstream_requests[-1]
    assert dict(request.url.params) == {"page": "1", "size": "40"}
    assert json.loads(request.content) == {"id": ORGANIZATION, "category": ["executive"]}


def _publisher(*items: Mapping[str, object]) -> dict[str, object]:
    return {"data": list(items), "hasNext": False}


def _item(entity: Mapping[str, object], *sources: str) -> dict[str, object]:
    return {
        "entity": entity,
        "relation": [
            {
                "type": "executive",
                "relationProperty": [
                    {"title": "director", "metadata": {"sourceName": source}} for source in sources
                ],
            }
        ],
    }


async def _page(
    mcp_client: McpClient, monkeypatch: pytest.MonkeyPatch, related: dict[str, object]
) -> contexts.RelatedPartiesPage:
    monkeypatch.setattr(polixis_responses, "RELATED_PARTIES", {"related": related})
    return await call_tool(
        mcp_client,
        "get_related_parties",
        {"pid": ORGANIZATION},
        returns=contexts.RelatedPartiesPage,
    )


async def test_get_related_parties_ranks_a_party_by_how_many_sources_report_it(
    mcp_client: McpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    one_source = {"pid": "P00000000000000000000000000000201", "names": [{"en": "Ava Example"}]}
    two_sources = {"pid": "P00000000000000000000000000000202", "names": [{"en": "Zoe Example"}]}

    page = await _page(
        mcp_client,
        monkeypatch,
        {
            "Register": _publisher(_item(one_source, "Register", "Register", "Register")),
            "Gazette": _publisher(_item(two_sources, "Register", "Gazette")),
        },
    )

    assert [party.name for party in page.parties] == ["Zoe Example", "Ava Example"]


async def test_get_related_parties_keeps_apart_two_parties_without_a_pid(
    mcp_client: McpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    namesake = {
        "type": "PERSON",
        "names": [{"en": "Pat Signatory"}],
        "flags": [{"PEP": {"value": "#PEP"}}],
    }

    page = await _page(
        mcp_client,
        monkeypatch,
        {
            "Register": _publisher(_item({**namesake, "flags": []}, "Register")),
            "Gazette": _publisher(_item(namesake, "Gazette")),
        },
    )

    assert [(party.name, party.flags) for party in page.parties] == [
        ("Pat Signatory", []),
        ("Pat Signatory", ["PEP"]),
    ]


async def test_get_related_parties_takes_a_name_only_a_later_publisher_gives(
    mcp_client: McpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = "P00000000000000000000000000000203"

    page = await _page(
        mcp_client,
        monkeypatch,
        {
            "Register": _publisher(_item({"pid": pid}, "Register")),
            "Gazette": _publisher(
                _item({"pid": pid, "type": "PERSON", "names": [{"en": "Eve"}]}, "Gazette")
            ),
        },
    )

    assert [(party.pid, party.name, party.entity_type) for party in page.parties] == [
        (pid, "Eve", "PERSON")
    ]


async def test_get_related_parties_keeps_a_relation_polixis_gives_no_details_for(
    mcp_client: McpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = "P00000000000000000000000000000204"
    item: dict[str, object] = {
        "entity": {"pid": pid},
        "relation": [{"type": "board"}, {"type": "executive", "relationProperty": []}],
    }

    page = await _page(mcp_client, monkeypatch, {"Register": _publisher(item)})

    assert [relation.relation_type for relation in page.parties[0].relations] == [
        "board",
        "executive",
    ]
