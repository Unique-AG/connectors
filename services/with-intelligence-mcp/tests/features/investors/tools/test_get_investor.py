"""`get_investor`: resolution, the entitlement distinction, and what the projection publishes."""

import httpx
import respx

from tests.helpers import BASE_URL, build_client, page_body, sent_query
from with_intelligence_mcp.features.investors import (
    InvestorAmbiguousResponse,
    InvestorNotFoundResponse,
    InvestorProfileResponse,
)
from with_intelligence_mcp.features.investors.tools.get_investor import get_investor

VIRGINIA: dict[str, object] = {
    "id": 2504,
    "name": "Virginia Retirement System",
    "updated_at": "2026-08-01",
    "summary": "Statewide public pension plan.",
    "website": "https://www.varetire.org",
    "year_of_incorporation": 1942,
    "aum": 112_000_000_000.0,
    "latest_aum": {"value": 115_000_000_000.0, "date": "2026-06-30", "currency": "USD"},
    "type": {"id": 7, "name": "Public Pension"},
    "address": {"city": "Richmond", "state": "Virginia", "country": "United States"},
    "contacts_total": 41,
    "contacts": [{"id": 88, "name": "A. Allocator"}],
    "managers": [{"id": 12, "name": "Bridgewater Associates"}],
    "consultants": [{"id": 99, "name": "Mercer"}],
    "primary_strategies": [{"id": 3, "name": "Equity Long/Short"}],
    "investment_countries": [{"id": 1, "name": "United States"}],
}


class TestResolvingByName:
    @respx.mock
    async def test_one_match_is_fetched_and_projected(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors").mock(
            return_value=httpx.Response(
                200, json=page_body([{"id": 2504, "name": "Virginia Retirement System"}], total=1)
            )
        )
        respx.get(f"{BASE_URL}/v3/investors/2504").mock(
            return_value=httpx.Response(200, json=VIRGINIA)
        )
        client, _ = build_client()
        result = await get_investor(name="Virginia Retirement System", client=client)
        assert isinstance(result, InvestorProfileResponse)
        assert result.id == 2504
        assert result.investor_type == "Public Pension"

    @respx.mock
    async def test_several_matches_ask_which_one(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors").mock(
            return_value=httpx.Response(
                200,
                json=page_body(
                    [{"id": 1, "name": "Mercer Global"}, {"id": 2, "name": "Mercer UK"}], total=2
                ),
            )
        )
        client, _ = build_client()
        result = await get_investor(name="Mercer", client=client)
        assert isinstance(result, InvestorAmbiguousResponse)
        assert [c.id for c in result.candidates] == [1, 2]
        assert result.total_matches == 2

    @respx.mock
    async def test_no_match_explains_how_the_name_filter_behaves(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors").mock(
            return_value=httpx.Response(200, json=page_body([], total=0))
        )
        client, _ = build_client()
        result = await get_investor(name="Nonexistent Pension", client=client)
        assert isinstance(result, InvestorNotFoundResponse)
        assert result.hint is not None
        assert "registered name" in result.hint

    @respx.mock
    async def test_the_search_asks_for_the_licensed_packages(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/investors").mock(
            return_value=httpx.Response(200, json=page_body([], total=0))
        )
        client, _ = build_client()
        _ = await get_investor(name="Anything", client=client)
        assert "asset_class_group=hfm" in sent_query(route)

    async def test_neither_argument_is_reported_not_guessed(self) -> None:
        client, _ = build_client()
        result = await get_investor(client=client)
        assert isinstance(result, InvestorNotFoundResponse)


class TestById:
    @respx.mock
    async def test_an_id_skips_resolution(self) -> None:
        search = respx.get(f"{BASE_URL}/v3/investors").mock(
            return_value=httpx.Response(200, json=page_body([], total=0))
        )
        respx.get(f"{BASE_URL}/v3/investors/2504").mock(
            return_value=httpx.Response(200, json=VIRGINIA)
        )
        client, _ = build_client()
        result = await get_investor(investor_id=2504, client=client)
        assert isinstance(result, InvestorProfileResponse)
        assert search.call_count == 0

    @respx.mock
    async def test_an_unknown_id_is_reported(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors/1").mock(return_value=httpx.Response(404))
        client, _ = build_client()
        result = await get_investor(investor_id=1, client=client)
        assert isinstance(result, InvestorNotFoundResponse)


class TestEntitlements:
    @respx.mock
    async def test_a_403_says_not_licensed_rather_than_not_found(self) -> None:
        """The distinction the whole connector has to preserve."""
        respx.get(f"{BASE_URL}/v3/investors").mock(return_value=httpx.Response(403))
        client, _ = build_client()
        result = await get_investor(name="Virginia Retirement System", client=client)
        assert isinstance(result, InvestorNotFoundResponse)
        assert result.hint is not None
        assert "licensed" in result.hint

    @respx.mock
    async def test_absent_preferences_are_flagged_as_unavailable(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors/2504").mock(
            return_value=httpx.Response(200, json=VIRGINIA)
        )
        client, _ = build_client()
        result = await get_investor(investor_id=2504, client=client)
        assert isinstance(result, InvestorProfileResponse)
        assert result.preferences_available is False
        assert result.preferences is None

    @respx.mock
    async def test_present_preferences_are_passed_through(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors/2504").mock(
            return_value=httpx.Response(
                200, json={**VIRGINIA, "preferences": {"hedge_funds": "increasing"}}
            )
        )
        client, _ = build_client()
        result = await get_investor(investor_id=2504, client=client)
        assert isinstance(result, InvestorProfileResponse)
        assert result.preferences_available is True


class TestProjection:
    @respx.mock
    async def test_prefers_the_dated_aum_over_the_bare_number(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors/2504").mock(
            return_value=httpx.Response(200, json=VIRGINIA)
        )
        client, _ = build_client()
        result = await get_investor(investor_id=2504, client=client)
        assert isinstance(result, InvestorProfileResponse)
        assert result.aum is not None
        assert result.aum.value == 115_000_000_000.0
        assert result.aum.as_of == "2026-06-30"

    @respx.mock
    async def test_falls_back_to_the_bare_aum_when_undated(self) -> None:
        record = {key: value for key, value in VIRGINIA.items() if key != "latest_aum"}
        respx.get(f"{BASE_URL}/v3/investors/2504").mock(
            return_value=httpx.Response(200, json=record)
        )
        client, _ = build_client()
        result = await get_investor(investor_id=2504, client=client)
        assert isinstance(result, InvestorProfileResponse)
        assert result.aum is not None
        assert result.aum.value == 112_000_000_000.0
        assert result.aum.as_of is None

    @respx.mock
    async def test_joins_the_address_into_one_location(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors/2504").mock(
            return_value=httpx.Response(200, json=VIRGINIA)
        )
        client, _ = build_client()
        result = await get_investor(investor_id=2504, client=client)
        assert isinstance(result, InvestorProfileResponse)
        assert result.location == "Richmond, Virginia, United States"

    @respx.mock
    async def test_keeps_vocabulary_ids_for_follow_up_filters(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors/2504").mock(
            return_value=httpx.Response(200, json=VIRGINIA)
        )
        client, _ = build_client()
        result = await get_investor(investor_id=2504, client=client)
        assert isinstance(result, InvestorProfileResponse)
        assert result.primary_strategies[0].id == 3
        assert result.primary_strategies[0].name == "Equity Long/Short"

    @respx.mock
    async def test_reports_the_contact_total_alongside_the_embedded_subset(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors/2504").mock(
            return_value=httpx.Response(200, json=VIRGINIA)
        )
        client, _ = build_client()
        result = await get_investor(investor_id=2504, client=client)
        assert isinstance(result, InvestorProfileResponse)
        assert len(result.contacts) == 1
        assert result.contacts_total == 41

    @respx.mock
    async def test_a_sparse_record_does_not_break_parsing(self) -> None:
        """Unmodelled and missing fields are both normal — the vendor has 40 of them."""
        respx.get(f"{BASE_URL}/v3/investors/7").mock(
            return_value=httpx.Response(200, json={"id": 7, "unexpected_field": {"a": 1}})
        )
        client, _ = build_client()
        result = await get_investor(investor_id=7, client=client)
        assert isinstance(result, InvestorProfileResponse)
        assert result.id == 7
        assert result.aum is None
        assert result.managers == []
