import httpx2
import pytest

from polixis_mcp import contexts
from tests import polixis_responses
from tests.tool_calls import call_tool
from tests.tool_calls import McpClient
from tests.tool_calls import tool_error


async def test_find_court_decisions_lists_those_naming_the_entity_first_without_their_text(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    found = await call_tool(
        mcp_client,
        "find_court_decisions",
        {"pid": "O00000000000000000000000000000100"},
        returns=contexts.CourtDecisionsPage,
    )

    assert upstream_requests[-1].url.path == "/api/judicial/O00000000000000000000000000000100"
    assert (found.total_decisions, found.total_naming_entity) == (2, 1)
    assert [decision.model_dump() for decision in found.decisions] == [
        {
            "decision_id": "ch_2019_1",
            "subject": "entity",
            "court_type": "Federal Court",
            "country": "CH",
            "year": "2019",
            "snippets": ["the appeal of Example Holdings AG is dismissed"],
            "text_characters": 40_000,
        },
        {
            "decision_id": "de_2023_7",
            "subject": "related_party",
            "court_type": "Regional Court",
            "country": "DE",
            "year": "2023",
            "snippets": ["Anna Example as witness"],
            "text_characters": 100,
        },
    ]


async def test_get_court_decision_returns_the_text_in_parts_of_about_8000_tokens(
    mcp_client: McpClient,
) -> None:
    first = await call_tool(
        mcp_client,
        "get_court_decision",
        {"pid": "O00000000000000000000000000000100", "decision_id": "ch_2019_1"},
        returns=contexts.CourtDecisionText,
    )
    rest = await call_tool(
        mcp_client,
        "get_court_decision",
        {"cursor": first.next_cursor},
        returns=contexts.CourtDecisionText,
    )

    assert (first.total_characters, len(first.text), first.subject) == (40_000, 32_000, "entity")
    assert (len(rest.text), rest.next_cursor) == (8_000, None)


async def test_get_court_decision_names_an_id_the_entity_does_not_have(
    mcp_client: McpClient,
) -> None:
    error = await tool_error(
        mcp_client,
        "get_court_decision",
        {"pid": "O00000000000000000000000000000100", "decision_id": "xx_1"},
    )

    assert error == (
        "Polixis has no decision xx_1 for O00000000000000000000000000000100. Take the id "
        "from `find_court_decisions` on the same pid."
    )


async def test_find_court_decisions_refuses_a_cursor_of_get_sanctions_exposure(
    mcp_client: McpClient,
) -> None:
    exposure = await call_tool(
        mcp_client,
        "get_sanctions_exposure",
        {"pid": "O00000000000000000000000000000100", "page_size": 1},
        returns=contexts.SanctionsExposurePage,
    )

    error = await tool_error(mcp_client, "find_court_decisions", {"cursor": exposure.next_cursor})

    assert error == "The cursor is not one this tool returned. Call the tool again without it."


async def test_find_court_decisions_lists_a_decision_whose_year_is_not_a_number(
    mcp_client: McpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    decision = {"id": "ch_x", "country": "ch", "year": "2\u00b2", "snippet": ["a"], "content": "C"}
    monkeypatch.setattr(polixis_responses, "JUDICIAL", {"rootJudicialDetails": {"ch": [decision]}})

    found = await call_tool(
        mcp_client,
        "find_court_decisions",
        {"pid": "O00000000000000000000000000000100"},
        returns=contexts.CourtDecisionsPage,
    )

    assert [decision.decision_id for decision in found.decisions] == ["ch_x"]
