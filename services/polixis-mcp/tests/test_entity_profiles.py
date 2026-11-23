import json

import httpx2
import pytest

from polixis_mcp import contexts
from tests import polixis_responses
from tests.polixis_responses import FAILING_PID
from tests.polixis_responses import UNKNOWN_PID
from tests.tool_calls import call_tool
from tests.tool_calls import McpClient
from tests.tool_calls import tool_error


async def test_get_entity_profiles_asks_polixis_for_the_key_identifiers_by_default(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    await mcp_client.call_tool(
        "get_entity_profiles", {"pids": ["P00000000000000000000000000000200"]}
    )

    completion = upstream_requests[-1]
    assert completion.url.path == "/api/completion/P00000000000000000000000000000200"
    assert json.loads(completion.content) == {
        "fields": [
            "nameRecords",
            "names",
            "unis",
            "countries",
            "dates",
            "flags",
            "alertList",
            "sanctionStatuses",
        ]
    }


async def test_get_entity_profiles_leaves_out_the_alerts_polixis_marks_hidden(
    mcp_client: McpClient,
) -> None:
    result = await call_tool(
        mcp_client,
        "get_entity_profiles",
        {"pids": ["P00000000000000000000000000000200"]},
        returns=contexts.EntityProfiles,
    )

    [profile] = result.results
    assert [alert.model_dump() for alert in profile.alerts or []] == [
        {"category": "PEP", "message": "Member of an example parliament"}
    ]


async def test_get_entity_profiles_gives_the_original_script_of_a_name_only_when_it_differs(
    mcp_client: McpClient,
) -> None:
    profiles = await call_tool(
        mcp_client,
        "get_entity_profiles",
        {"pids": ["P00000000000000000000000000000200"], "sections": ["name_records"]},
        returns=contexts.EntityProfiles,
    )

    [profile] = profiles.results
    assert [record.model_dump() for record in profile.name_records or []] == [
        {
            "name": "Anna Example",
            "original": "Anna Beispiel",
            "language": "de",
            "kind": "CURRENT_NAME",
        }
    ]


async def test_get_entity_profiles_returns_only_the_sections_asked_for(
    mcp_client: McpClient,
) -> None:
    profiles = await call_tool(
        mcp_client,
        "get_entity_profiles",
        {"pids": ["P00000000000000000000000000000200"], "sections": ["sanctions", "positions"]},
        returns=contexts.EntityProfiles,
    )

    [profile] = profiles.results
    assert [listing.model_dump() for listing in profile.sanctions or []] == [
        {
            "list_name": "Example Sanctions List",
            "country": "CH",
            "status": "DELISTED",
            "details": {"Sanction Status": ["DELISTED"], "Program": ["Example programme"]},
        }
    ]
    assert [position.model_dump() for position in profile.positions or []] == [
        {
            "position": "Member of Parliament",
            "institution": "Example Parliament",
            "start_date": "2015",
            "end_date": "2023-12-31",
            "remark": None,
        }
    ]
    assert profile.names is None
    assert profile.flags is None


async def test_get_entity_profiles_looks_up_every_pid_and_marks_an_unknown_one(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    profiles = await call_tool(
        mcp_client,
        "get_entity_profiles",
        {
            "pids": [
                "P00000000000000000000000000000200",
                UNKNOWN_PID,
                "P00000000000000000000000000000200",
            ],
            "sections": ["flags", "dates"],
        },
        returns=contexts.EntityProfiles,
    )

    known, unknown = profiles.results
    assert (known.pid, known.rejected, known.flags) == (
        "P00000000000000000000000000000200",
        None,
        ["PEP", "SANCTION", "REP"],
    )
    assert known.dates == {"Date of Birth": ["1971-03"]}
    assert unknown.pid == UNKNOWN_PID
    assert unknown.rejected == (
        f"Polixis rejected the request (VALIDATION): Invalid Ardis ID: {UNKNOWN_PID}"
    )
    completions = [r for r in upstream_requests if r.url.path.startswith("/api/completion/")]
    assert len(completions) == 2


async def test_get_entity_profiles_refuses_more_than_ten_pids(mcp_client: McpClient) -> None:
    await tool_error(mcp_client, "get_entity_profiles", {"pids": [f"P{n:032x}" for n in range(11)]})


async def test_get_entity_profiles_reports_the_polixis_error_of_a_failed_lookup(
    mcp_client: McpClient,
) -> None:
    error = await tool_error(
        mcp_client,
        "get_entity_profiles",
        {"pids": ["P00000000000000000000000000000200", FAILING_PID]},
    )

    assert error.startswith(
        f"500 Internal Server Error for POST https://api.example.com/api/completion/{FAILING_PID}"
    )


async def test_get_entity_profiles_refuses_a_malformed_pid_without_asking_polixis(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    error = await tool_error(
        mcp_client, "get_entity_profiles", {"pids": ["P00000000000000000000000000000200", "O123"]}
    )

    assert "O123" in error
    assert upstream_requests == []


async def test_get_entity_profiles_lists_the_names_under_every_key(
    mcp_client: McpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = {"original": ["Anna Beispiel"], "de": ["Anna B."], "en": ["Anna Example"]}
    monkeypatch.setattr(polixis_responses, "PROFILE", {"names": names})

    result = await call_tool(
        mcp_client,
        "get_entity_profiles",
        {"pids": ["P00000000000000000000000000000200"], "sections": ["names"]},
        returns=contexts.EntityProfiles,
    )

    assert result.results[0].names == ["Anna Example", "Anna Beispiel", "Anna B."]


async def test_get_entity_profiles_returns_the_image_urls_when_asked(
    mcp_client: McpClient,
    monkeypatch: pytest.MonkeyPatch,
    upstream_requests: list[httpx2.Request],
) -> None:
    image = "https://images.example.com/anna.jpeg"
    monkeypatch.setattr(polixis_responses, "PROFILE", {"images": [image, image]})

    result = await call_tool(
        mcp_client,
        "get_entity_profiles",
        {"pids": ["P00000000000000000000000000000200"], "sections": ["images"]},
        returns=contexts.EntityProfiles,
    )

    assert json.loads(upstream_requests[-1].content) == {
        "fields": ["nameRecords", "names", "images"]
    }
    assert result.results[0].images == [image]


async def test_get_entity_profiles_names_a_profile_whichever_sections_are_asked_for(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    profiles = await call_tool(
        mcp_client,
        "get_entity_profiles",
        {"pids": ["P00000000000000000000000000000200"], "sections": ["flags"]},
        returns=contexts.EntityProfiles,
    )

    [profile] = profiles.results
    assert (profile.name, profile.name_records) == ("Anna Example", None)
    assert json.loads(upstream_requests[-1].content) == {
        "fields": ["nameRecords", "names", "flags"]
    }


async def test_get_entity_profiles_names_a_profile_without_name_records_by_its_first_name(
    mcp_client: McpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        polixis_responses, "PROFILE", {"names": {"en": ["Anna Example"]}, "flags": ["PEP"]}
    )

    profiles = await call_tool(
        mcp_client,
        "get_entity_profiles",
        {"pids": ["P00000000000000000000000000000200"], "sections": ["flags"]},
        returns=contexts.EntityProfiles,
    )

    [profile] = profiles.results
    assert (profile.name, profile.names) == ("Anna Example", None)


async def test_get_entity_profiles_leaves_a_rejected_pid_unnamed(mcp_client: McpClient) -> None:
    profiles = await call_tool(
        mcp_client,
        "get_entity_profiles",
        {"pids": [UNKNOWN_PID]},
        returns=contexts.EntityProfiles,
    )

    assert profiles.results[0].name is None
