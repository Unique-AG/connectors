import httpx2
import pytest

from polixis_mcp import contexts
from polixis_mcp.contexts.pages import encode_cursor
from tests import polixis_responses
from tests.polixis_responses import UNKNOWN_PID
from tests.tool_calls import call_tool
from tests.tool_calls import McpClient
from tests.tool_calls import tool_error


async def test_get_ultimate_beneficial_owners_ranks_owners_by_their_summed_effective_share(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    page = await call_tool(
        mcp_client,
        "get_ultimate_beneficial_owners",
        {"pid": "O00000000000000000000000000000100"},
        returns=contexts.OwnershipPage,
    )

    assert upstream_requests[-1].url.path == "/api/graph/ubo/O00000000000000000000000000000100"
    assert (page.total_entities, page.truncated_by_polixis, page.next_cursor) == (3, False, None)
    assert page.total_share_unknown == 0
    assert [
        (entity.name, entity.effective_share_percent, entity.depth, entity.chains)
        for entity in page.entities
    ] == [
        ("Example Parent AG", 80.0, 1, 1),
        ("Carla Sample", 50.0, 1, 2),
        ("Anna Example", 20.0, 1, 1),
    ]


async def test_get_ultimate_beneficial_owners_counts_an_owner_listed_twice_under_one_parent_once(
    mcp_client: McpClient,
) -> None:
    page = await call_tool(
        mcp_client,
        "get_ultimate_beneficial_owners",
        {"pid": "O00000000000000000000000000000100"},
        returns=contexts.OwnershipPage,
    )

    owner = page.entities[2]
    assert (owner.name, owner.effective_share_percent, owner.chains) == ("Anna Example", 20.0, 1)
    assert (owner.direct_share_percent, owner.roles) == (20.0, ["shareholder", "beneficial owner"])


async def test_get_ultimate_beneficial_owners_keeps_the_strongest_chain_of_an_owner(
    mcp_client: McpClient,
) -> None:
    page = await call_tool(
        mcp_client,
        "get_ultimate_beneficial_owners",
        {"pid": "O00000000000000000000000000000100"},
        returns=contexts.OwnershipPage,
    )

    owner = page.entities[1]
    assert (owner.direct_share_percent, owner.end_of_chain, owner.flags) == (10.0, True, ["PEP"])
    assert owner.roles == ["shareholder", "reported shareholder"]
    assert [(link.pid, link.share_percent) for link in owner.strongest_chain] == [
        ("O00000000000000000000000000000600", 80.0),
        ("P00000000000000000000000000000700", 50.0),
    ]
    assert page.entities[0].end_of_chain is False


async def test_get_ultimate_beneficial_owners_lists_the_sanctioned_owners_first_on_the_first_page(
    mcp_client: McpClient,
) -> None:
    first = await call_tool(
        mcp_client,
        "get_ultimate_beneficial_owners",
        {"pid": "O00000000000000000000000000000100", "page_size": 1},
        returns=contexts.OwnershipPage,
    )
    second = await call_tool(
        mcp_client,
        "get_ultimate_beneficial_owners",
        {"cursor": first.next_cursor},
        returns=contexts.OwnershipPage,
    )

    assert first.total_flagged == 2
    assert (first.total_by_risk["SANCTION"], first.total_by_risk["PEP"]) == (1, 1)
    assert [(flag.name, flag.effective_share_percent, flag.risks) for flag in first.flagged] == [
        ("Anna Example", 20.0, ["SANCTION"]),
        ("Carla Sample", 50.0, ["PEP"]),
    ]
    assert [entity.pid for entity in second.entities] == ["P00000000000000000000000000000700"]
    assert (second.total_flagged, second.flagged) == (2, [])


async def test_get_top_down_ownership_leaves_an_unreported_share_unknown(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    page = await call_tool(
        mcp_client,
        "get_top_down_ownership",
        {"pid": "O00000000000000000000000000000100"},
        returns=contexts.OwnershipPage,
    )

    assert upstream_requests[-1].url.path == "/api/graph/topdown/O00000000000000000000000000000100"
    assert page.truncated_by_polixis is True
    holding, minority = page.entities
    assert (holding.name, holding.alerts) == ("Example Shipping Ltd", ["STATECO"])
    assert (minority.effective_share_percent, minority.share_unknown_on_some_chain) == (None, True)
    assert page.total_share_unknown == 1
    assert [flag.risks for flag in page.flagged] == [["STATECO"]]


async def test_ownership_reports_an_id_polixis_rejects(mcp_client: McpClient) -> None:
    error = await tool_error(mcp_client, "get_ultimate_beneficial_owners", {"pid": UNKNOWN_PID})

    assert error == f"Polixis rejected the request (VALIDATION): Invalid Ardis ID: {UNKNOWN_PID}"


async def test_ownership_refuses_a_cursor_of_another_tool(mcp_client: McpClient) -> None:
    search = await call_tool(
        mcp_client,
        "search_entities",
        {"name": "Example Holdings"},
        returns=contexts.EntitySearchResults,
    )

    error = await tool_error(
        mcp_client, "get_ultimate_beneficial_owners", {"cursor": search.next_cursor}
    )

    assert error == "The cursor is not one this tool returned. Call the tool again without it."


async def test_top_down_ownership_refuses_a_cursor_of_the_beneficial_owners(
    mcp_client: McpClient,
) -> None:
    owners = await call_tool(
        mcp_client,
        "get_ultimate_beneficial_owners",
        {"pid": "O00000000000000000000000000000100", "page_size": 1},
        returns=contexts.OwnershipPage,
    )

    error = await tool_error(mcp_client, "get_top_down_ownership", {"cursor": owners.next_cursor})

    assert error == "The cursor is not one this tool returned. Call the tool again without it."


@pytest.mark.parametrize(
    ("arguments", "error"),
    [
        ({}, "Missing or invalid: pid. Pass them, or the `cursor` of a page."),
        (
            {"cursor": "not-a-cursor"},
            "The cursor is not one this tool returned. Call the tool again without it.",
        ),
    ],
)
async def test_ownership_needs_a_pid_or_a_cursor(
    mcp_client: McpClient, arguments: dict[str, object], error: str
) -> None:
    assert await tool_error(mcp_client, "get_top_down_ownership", arguments) == error


async def test_a_page_holds_the_rows_that_fit_in_its_token_budget(
    mcp_client: McpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The rows of the fake tree cost about 84, 102 and 87 tokens: a page fits one.
    monkeypatch.setattr("polixis_mcp.contexts.pages.PAGE_TOKENS", 100)

    first = await call_tool(
        mcp_client,
        "get_ultimate_beneficial_owners",
        {"pid": "O00000000000000000000000000000100"},
        returns=contexts.OwnershipPage,
    )
    rest = await call_tool(
        mcp_client,
        "get_ultimate_beneficial_owners",
        {"cursor": first.next_cursor},
        returns=contexts.OwnershipPage,
    )

    assert [entity.pid for entity in first.entities] == ["O00000000000000000000000000000600"]
    assert [entity.pid for entity in rest.entities] == ["P00000000000000000000000000000700"]
    assert rest.next_cursor is not None


async def test_a_page_size_caps_the_rows_below_the_token_budget(mcp_client: McpClient) -> None:
    page = await call_tool(
        mcp_client,
        "get_ultimate_beneficial_owners",
        {"pid": "O00000000000000000000000000000100", "page_size": 2},
        returns=contexts.OwnershipPage,
    )

    assert [entity.pid for entity in page.entities] == [
        "O00000000000000000000000000000600",
        "P00000000000000000000000000000700",
    ]
    assert page.next_cursor is not None


async def test_a_malformed_pid_is_refused_without_asking_polixis(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    error = await tool_error(mcp_client, "get_ultimate_beneficial_owners", {"pid": "O123"})

    assert "O123" in error
    assert upstream_requests == []


async def test_ownership_reaches_the_owners_behind_a_node_without_an_id(
    mcp_client: McpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = {"id": "P00000000000000000000000000000700", "type": "PERSON", "sharePercent": 50.0}
    anonymous = {"type": "ORGANIZATION", "sharePercent": 80.0, "children": [owner]}
    monkeypatch.setattr(polixis_responses, "OWNERS", {"roots": [anonymous]})

    page = await call_tool(
        mcp_client,
        "get_ultimate_beneficial_owners",
        {"pid": "O00000000000000000000000000000100"},
        returns=contexts.OwnershipPage,
    )

    assert [(entity.pid, entity.effective_share_percent) for entity in page.entities] == [
        ("P00000000000000000000000000000700", 40.0)
    ]


async def test_ownership_refuses_a_cursor_carrying_a_malformed_pid(mcp_client: McpClient) -> None:
    forged = encode_cursor(
        contexts.OwnershipQuery.model_construct(
            pid="../../api/sanction/O1", direction="owners", page_size=None, offset=0
        )
    )

    error = await tool_error(mcp_client, "get_ultimate_beneficial_owners", {"cursor": forged})

    assert error == "The cursor is not one this tool returned. Call the tool again without it."


async def test_ownership_keeps_apart_two_owners_without_an_id_on_the_way_to_one_owner(
    mcp_client: McpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = {"id": "P00000000000000000000000000000700", "type": "PERSON", "sharePercent": 50.0}
    roots = [{"type": "ORGANIZATION", "sharePercent": 50.0, "children": [owner]} for _ in range(2)]
    monkeypatch.setattr(polixis_responses, "OWNERS", {"roots": roots})

    page = await call_tool(
        mcp_client,
        "get_ultimate_beneficial_owners",
        {"pid": "O00000000000000000000000000000100"},
        returns=contexts.OwnershipPage,
    )

    assert [
        (entity.pid, entity.effective_share_percent, entity.chains) for entity in page.entities
    ] == [("P00000000000000000000000000000700", 50.0, 2)]


async def test_ownership_refuses_a_cursor_issued_over_other_rows(mcp_client: McpClient) -> None:
    stale = encode_cursor(
        contexts.OwnershipQuery(
            pid="O00000000000000000000000000000100",
            direction="owners",
            page_size=1,
            offset=1,
            snapshot="0000000000000000",
        )
    )

    error = await tool_error(mcp_client, "get_ultimate_beneficial_owners", {"cursor": stale})

    assert error == (
        "The result changed since the previous page, so this cursor would skip or repeat rows. "
        "Call the tool again without it."
    )
