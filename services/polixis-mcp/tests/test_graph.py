import json

import httpx2

from polixis_mcp import contexts
from tests.polixis_responses import FAILING_PID
from tests.tool_calls import call_tool
from tests.tool_calls import McpClient
from tests.tool_calls import tool_error


async def test_find_linked_companies_lists_direct_ties_before_ties_through_people(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    found = await call_tool(
        mcp_client,
        "find_linked_companies",
        {"pid": "O00000000000000000000000000000100"},
        returns=contexts.LinkedCompaniesPage,
    )

    request = upstream_requests[-1]
    assert request.url.path == "/api/graph/smart"
    assert json.loads(request.content) == {"id": "O00000000000000000000000000000100", "radius": 2}
    assert (found.total_companies, found.total_direct, found.total_flagged) == (2, 1, 1)
    assert found.total_by_risk["STATECO"] == 1
    assert found.truncated_by_polixis is False
    direct, through_person = found.results
    assert (direct.company.name, direct.through_total) == ("Example Shipping Ltd", 0)
    assert direct.direct_links[0].relations[0].share_percent == 100.0
    assert (through_person.company.name, through_person.risks) == (
        "Example Consulting GmbH",
        ["STATECO"],
    )
    assert through_person.direct_links == []
    assert (direct.hops, through_person.hops) == (1, 2)
    [chain] = through_person.through
    assert [person.name for person in chain.people] == ["Pia Example"]
    assert [(link.source_pid, link.target_pid) for link in chain.links] == [
        ("P00000000000000000000000000000210", "O00000000000000000000000000000100"),
        ("P00000000000000000000000000000210", "O00000000000000000000000000000310"),
    ]


async def test_find_linked_companies_follows_two_people_in_a_row_at_radius_3(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    found = await call_tool(
        mcp_client,
        "find_linked_companies",
        {"pid": "O00000000000000000000000000000100", "radius": 3},
        returns=contexts.LinkedCompaniesPage,
    )

    assert json.loads(upstream_requests[-1].content) == {
        "id": "O00000000000000000000000000000100",
        "radius": 3,
    }
    assert [(linked.company.pid, linked.hops) for linked in found.results] == [
        ("O00000000000000000000000000000300", 1),
        ("O00000000000000000000000000000310", 2),
        ("O00000000000000000000000000000320", 3),
    ]
    [chain] = found.results[2].through
    assert [person.name for person in chain.people] == ["Pia Example", "Paul Sample"]
    assert [link.relations[0].role for link in chain.links] == [
        "director",
        "business partner",
        "owner",
    ]


async def test_find_linked_companies_adds_minor_ties_from_the_full_graph(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    found = await call_tool(
        mcp_client,
        "find_linked_companies",
        {"pid": "O00000000000000000000000000000100", "scope": "all", "page_size": 2},
        returns=contexts.LinkedCompaniesPage,
    )
    rest = await call_tool(
        mcp_client,
        "find_linked_companies",
        {"cursor": found.next_cursor},
        returns=contexts.LinkedCompaniesPage,
    )

    assert {request.url.path for request in upstream_requests[-2:]} == {
        "/api/graph/smart",
        "/api/graph/subgraph",
    }
    assert (found.total_companies, found.total_direct) == (3, 2)
    assert found.truncated_by_polixis is True
    assert [linked.company.pid for linked in [*found.results, *rest.results]] == [
        "O00000000000000000000000000000500",
        "O00000000000000000000000000000300",
        "O00000000000000000000000000000310",
    ]


async def test_find_connections_orders_the_steps_of_the_path_polixis_finds(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    connections = await call_tool(
        mcp_client,
        "find_connections",
        {
            "from_pid": "P00000000000000000000000000000200",
            "to_pid": "P00000000000000000000000000000400",
        },
        returns=contexts.Connections,
    )

    request = upstream_requests[-1]
    assert request.url.path == "/api/graph/path"
    assert json.loads(request.content) == {
        "sourceId": "P00000000000000000000000000000200",
        "targetId": "P00000000000000000000000000000400",
    }
    assert (connections.connected, connections.hops) == (True, 3)
    [path] = connections.paths
    assert path.ordered is True
    assert [(step.from_name, step.to_name) for step in path.steps] == [
        ("Anna Example", "Example Holdings AG"),
        ("Example Holdings AG", "Example Shipping Ltd"),
        ("Example Shipping Ltd", "Boris Sample"),
    ]
    assert path.steps[2].links[0].relations[0].role == "director"
    assert [(party.pid, party.flags, party.alerts) for party in connections.results] == [
        ("P00000000000000000000000000000200", ["PEP"], []),
        ("O00000000000000000000000000000100", [], []),
        ("O00000000000000000000000000000300", [], ["STATECO"]),
        ("P00000000000000000000000000000400", ["SANCTION"], []),
    ]


async def test_find_connections_reports_a_path_that_does_not_start_at_the_pid_asked_about(
    mcp_client: McpClient,
) -> None:
    merged_pid = "P00000000000000000000000000000250"
    connections = await call_tool(
        mcp_client,
        "find_connections",
        {"from_pid": merged_pid, "to_pid": "P00000000000000000000000000000400"},
        returns=contexts.Connections,
    )

    assert (connections.connected, connections.hops) == (True, 3)
    [path] = connections.paths
    assert path.ordered is False
    assert [(step.from_name, step.to_name) for step in path.steps] == [
        ("Boris Sample", "Example Shipping Ltd"),
        ("Anna Example", "Example Holdings AG"),
        ("Example Holdings AG", "Example Shipping Ltd"),
    ]


async def test_find_connections_says_when_none_was_found(mcp_client: McpClient) -> None:
    connections = await call_tool(
        mcp_client,
        "find_connections",
        {
            "from_pid": "O00000000000000000000000000000100",
            "to_pid": "O00000000000000000000000000000999",
        },
        returns=contexts.Connections,
    )

    assert (connections.connected, connections.hops, connections.paths) == (False, None, [])


async def test_find_flagged_parties_lists_the_most_severe_first_with_the_path_to_each(
    mcp_client: McpClient,
) -> None:
    found = await call_tool(
        mcp_client,
        "find_flagged_parties",
        {"pid": "O00000000000000000000000000000100", "radius": 2},
        returns=contexts.FlaggedPartiesPage,
    )

    assert found.parties_checked == 8
    assert [(flagged.party.pid, flagged.risks, len(flagged.path)) for flagged in found.results] == [
        ("P00000000000000000000000000000400", ["SANCTION"], 2),
        ("P00000000000000000000000000000200", ["PEP"], 1),
        ("O00000000000000000000000000000500", ["STATECO"], 1),
        ("O00000000000000000000000000000310", ["STATECO"], 2),
    ]
    assert found.results[2].party.name is None
    assert found.total_by_risk == {
        "FORMER_PEP": 0,
        "PEP": 1,
        "REP": 0,
        "RESTRICTION": 0,
        "SANCTION": 1,
        "SANCTIONTERRITORY": 0,
        "STATECO": 2,
    }


async def test_find_flagged_parties_says_when_polixis_cut_the_network_short(
    mcp_client: McpClient,
) -> None:
    found = await call_tool(
        mcp_client,
        "find_flagged_parties",
        {"pid": "O00000000000000000000000000000100"},
        returns=contexts.FlaggedPartiesPage,
    )

    assert found.truncated_by_polixis is True


async def test_find_flagged_parties_reports_the_polixis_error_of_a_failed_graph(
    mcp_client: McpClient,
) -> None:
    error = await tool_error(mcp_client, "find_flagged_parties", {"pid": FAILING_PID})

    assert error.startswith(
        "500 Internal Server Error for POST https://api.example.com/api/graph/subgraph"
    )


async def test_find_flagged_parties_has_polixis_filter_both_graphs_on_every_hop(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    await call_tool(
        mcp_client,
        "find_flagged_parties",
        {
            "pid": "O00000000000000000000000000000100",
            "radius": 2,
            "current_only": True,
            "sanctioned_only": True,
        },
        returns=contexts.FlaggedPartiesPage,
    )

    rule = {"direction": "BOTH", "onlyActual": True, "requireSanction": True}
    graphs = {
        request.url.path: json.loads(request.content)
        for request in upstream_requests
        if request.url.path in {"/api/graph/smart", "/api/graph/subgraph"}
    }
    assert graphs == {
        path: {
            "id": "O00000000000000000000000000000100",
            "radius": 2,
            "filter": {"rules": {"1": rule, "2": rule}},
        }
        for path in ("/api/graph/smart", "/api/graph/subgraph")
    }
