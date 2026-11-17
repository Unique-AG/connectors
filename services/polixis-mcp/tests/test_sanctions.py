import httpx2
import pytest

from polixis_mcp import contexts
from tests import polixis_responses
from tests.polixis_responses import UNKNOWN_PID
from tests.tool_calls import call_tool
from tests.tool_calls import McpClient
from tests.tool_calls import tool_error


async def test_get_sanctions_exposure_gives_the_own_listings_and_the_nearest_parties_first(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    exposure = await call_tool(
        mcp_client,
        "get_sanctions_exposure",
        {"pid": "O00000000000000000000000000000100"},
        returns=contexts.SanctionsExposurePage,
    )

    assert upstream_requests[-1].url.path == "/api/sanction/O00000000000000000000000000000100"
    assert [listing.model_dump() for listing in exposure.own_listings] == [
        {
            "list_name": "Example Autonomous Sanctions",
            "country": "CA",
            "status": "ACTIVE",
            "programs": [],
            "listed_on": "2022-02-24",
        }
    ]
    assert exposure.total_related == 3
    assert [(party.pid, party.hops) for party in exposure.related] == [
        ("O00000000000000000000000000000900", 1),
        ("P00000000000000000000000000000400", 2),
        (None, None),
    ]
    assert exposure.related[0].path[0].start_date == "2013-12-31"
    assert exposure.related[0].listings[0].listed_on == "2024-06-13"


async def test_get_sanctions_exposure_keeps_every_relation_on_the_path(
    mcp_client: McpClient,
) -> None:
    exposure = await call_tool(
        mcp_client,
        "get_sanctions_exposure",
        {"pid": "O00000000000000000000000000000100", "page_size": 1},
        returns=contexts.SanctionsExposurePage,
    )
    rest = await call_tool(
        mcp_client,
        "get_sanctions_exposure",
        {"cursor": exposure.next_cursor},
        returns=contexts.SanctionsExposurePage,
    )

    [party] = rest.related
    assert [
        (listing.status, listing.programs, listing.listed_on) for listing in party.listings
    ] == [("ACTIVE", ["EXAMPLE-EO1"], "2022-04-14")]
    assert [(link.role, link.former) for link in party.path] == [
        ("shareholder/ founder", False),
        ("reported shareholder", False),
        ("director", True),
    ]
    assert rest.next_cursor is not None


async def test_get_sanctions_exposure_reports_an_id_polixis_rejects(
    mcp_client: McpClient,
) -> None:
    error = await tool_error(mcp_client, "get_sanctions_exposure", {"pid": UNKNOWN_PID})

    assert error == f"Polixis rejected the request (VALIDATION): Invalid Ardis ID: {UNKNOWN_PID}"


async def test_get_sanctions_exposure_leaves_the_distance_unknown_past_an_unnamed_party(
    mcp_client: McpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    unnamed = {"connection": {"role": "shareholder"}, "sourceName": "Example Holdings AG"}
    named = {"connection": {"role": "director"}, "sourceName": "Bo", "targetName": "Example Ltd"}
    monkeypatch.setattr(
        polixis_responses,
        "SANCTION_EXPOSURE",
        {
            "relatedSanctions": [
                {"pid": "P00000000000000000000000000000401", "relationPaths": [unnamed, unnamed]},
                {"pid": "P00000000000000000000000000000402", "relationPaths": [named]},
            ]
        },
    )

    exposure = await call_tool(
        mcp_client,
        "get_sanctions_exposure",
        {"pid": "O00000000000000000000000000000100"},
        returns=contexts.SanctionsExposurePage,
    )

    assert [(party.pid, party.hops) for party in exposure.related] == [
        ("P00000000000000000000000000000402", 1),
        ("P00000000000000000000000000000401", None),
    ]


async def test_get_sanctions_exposure_keeps_a_sanctioned_party_without_a_pid(
    mcp_client: McpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = [{"connection": {"role": "director"}, "sourceName": "Bo", "targetName": "Example Ltd"}]
    monkeypatch.setattr(
        polixis_responses,
        "SANCTION_EXPOSURE",
        {"relatedSanctions": [{"nameEn": "Unregistered Sample", "relationPaths": path}]},
    )

    exposure = await call_tool(
        mcp_client,
        "get_sanctions_exposure",
        {"pid": "O00000000000000000000000000000100"},
        returns=contexts.SanctionsExposurePage,
    )

    assert exposure.total_related == 1
    assert [(party.pid, party.name, party.hops) for party in exposure.related] == [
        (None, "Unregistered Sample", 1)
    ]
