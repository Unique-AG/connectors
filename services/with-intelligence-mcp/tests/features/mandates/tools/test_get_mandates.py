"""`get_mandates`: status vocabulary, staleness, notes, and what won."""

import httpx
import respx

from tests.helpers import BASE_URL, build_client, page_body, sent_query
from with_intelligence_mcp.features.investors import (
    InvestorAmbiguousResponse,
    InvestorNotEntitledResponse,
    InvestorNotFoundResponse,
)
from with_intelligence_mcp.features.investors.queries import ResolveInvestorRecordQuery
from with_intelligence_mcp.features.mandates import InvestorMandatesResponse
from with_intelligence_mcp.features.mandates.queries import GetMandatesQuery
from with_intelligence_mcp.features.mandates.tools.get_mandates import (
    get_mandates as call_get_mandates,
)
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient


async def get_mandates(
    *,
    client: WithIntelligenceClient,
    name: str | None = None,
    investor_id: int | None = None,
    page: int = 1,
    limit: int = 25,
    updated_since: str | None = None,
) -> (
    InvestorMandatesResponse
    | InvestorAmbiguousResponse
    | InvestorNotEntitledResponse
    | InvestorNotFoundResponse
):
    return await call_get_mandates(
        name=name,
        investor_id=investor_id,
        page=page,
        limit=limit,
        updated_since=updated_since,
        resolve_investor_record_query=ResolveInvestorRecordQuery(client),
        get_mandates_query=GetMandatesQuery(client=client),
    )


INVESTOR: dict[str, object] = {"id": 2504, "name": "Example Retirement System (ERS)"}

OPEN_SEARCH: dict[str, object] = {
    "id": 21,
    "updated_at": "2026-08-01",
    "status": {"id": 1, "name": "Open", "sub_status": {"id": 4, "name": "Shortlisting"}},
    "service": {"id": 2, "name": "Manager Search"},
    "amount": {"amount": 300.0, "currency": {"short_name": "USD"}},
    "asset_class": [{"id": 1, "name": "Hedge Funds"}],
    "primary_strategies": [{"id": 77, "name": "Equity"}],
    "secondary_strategies": [{"id": 78, "name": "Long/Short Equity"}],
    "fund_structures": [{"id": 2, "name": "Managed Account"}],
    "market_focuses": [{"id": 3, "name": "Developed Markets"}],
    "consultant": "A. Consultant",
    "primary_consultant_firm": {"id": 99, "name": "Consultant One"},
    "rfp_link": "https://example.invalid/rfp",
    "last_reviewed": {"date": "2026-07-15"},
    "note": "Reviewing managers this quarter.",
    "notes": [
        {"date": "2026-05-01", "note": "Mandate opened."},
        {"date": "2026-07-15", "note": "Shortlist drawn up."},
        {"note": "Undated remark."},
    ],
}

AWARDED: dict[str, object] = {
    "id": 22,
    "status": {"id": 3, "name": "Completed"},
    "fund": {"id": 900, "name": "Example Macro Fund"},
    "last_reviewed": {"date": "2024-01-31"},
}


def _mock(mandates: list[dict[str, object]], *, total: int | None = None) -> None:
    listing = [{"id": m["id"], "updated_at": "2026-08-01"} for m in mandates]
    respx.get(f"{BASE_URL}/v3/mandates").mock(
        return_value=httpx.Response(
            200, json=page_body(listing, total=total if total is not None else len(mandates))
        )
    )
    for mandate in mandates:
        respx.get(f"{BASE_URL}/v3/mandates/{mandate['id']}").mock(
            return_value=httpx.Response(200, json=mandate)
        )
    respx.get(f"{BASE_URL}/v3/investors/2504").mock(return_value=httpx.Response(200, json=INVESTOR))


class TestStatus:
    @respx.mock
    async def test_reports_status_and_sub_status_verbatim(self) -> None:
        """Reports the status vocabulary verbatim."""
        _mock([OPEN_SEARCH])
        client, _ = build_client()
        result = await get_mandates(investor_id=2504, client=client)
        assert isinstance(result, InvestorMandatesResponse)
        mandate = result.mandates[0]
        assert mandate.status == "Open"
        assert mandate.sub_status == "Shortlisting"
        assert mandate.service == "Manager Search"

    @respx.mock
    async def test_surfaces_last_reviewed_so_staleness_is_visible(self) -> None:
        """A mandate can read Open and have gone untouched for two years."""
        _mock([AWARDED])
        client, _ = build_client()
        result = await get_mandates(investor_id=2504, client=client)
        assert isinstance(result, InvestorMandatesResponse)
        assert result.mandates[0].last_reviewed == "2024-01-31"

    @respx.mock
    async def test_names_the_fund_that_won_it(self) -> None:
        _mock([AWARDED])
        client, _ = build_client()
        result = await get_mandates(investor_id=2504, client=client)
        assert isinstance(result, InvestorMandatesResponse)
        assert result.mandates[0].awarded_to == "Example Macro Fund"


class TestWhatTheyAreLookingFor:
    @respx.mock
    async def test_sparse_detail_keeps_omitted_collections_unknown(self) -> None:
        _mock([{"id": 21}])
        client, _ = build_client()
        result = await get_mandates(investor_id=2504, client=client)
        assert isinstance(result, InvestorMandatesResponse)
        mandate = result.mandates[0]
        assert mandate.asset_classes is None
        assert mandate.strategies is None
        assert mandate.structures is None
        assert mandate.market_focuses is None

    @respx.mock
    async def test_an_unavailable_detail_keeps_unknown_collections_unknown(self) -> None:
        respx.get(f"{BASE_URL}/v3/mandates").mock(
            return_value=httpx.Response(
                200,
                json=page_body([{"id": 21, "updated_at": "2026-08-01"}], total=1),
            )
        )
        respx.get(f"{BASE_URL}/v3/mandates/21").mock(return_value=httpx.Response(403))
        respx.get(f"{BASE_URL}/v3/investors/2504").mock(
            return_value=httpx.Response(200, json=INVESTOR)
        )
        client, _ = build_client()
        result = await get_mandates(investor_id=2504, client=client)
        assert isinstance(result, InvestorMandatesResponse)
        mandate = result.mandates[0]
        assert mandate.asset_classes is None
        assert mandate.strategies is None
        assert mandate.structures is None
        assert mandate.market_focuses is None

    @respx.mock
    async def test_strategies_structures_and_focus_come_through(self) -> None:
        _mock([OPEN_SEARCH])
        client, _ = build_client()
        result = await get_mandates(investor_id=2504, client=client)
        assert isinstance(result, InvestorMandatesResponse)
        mandate = result.mandates[0]
        assert mandate.strategies == ["Equity", "Long/Short Equity"]
        assert mandate.structures == ["Managed Account"]
        assert mandate.market_focuses == ["Developed Markets"]

    @respx.mock
    async def test_the_size_is_labelled_as_millions(self) -> None:
        _mock([OPEN_SEARCH])
        client, _ = build_client()
        result = await get_mandates(investor_id=2504, client=client)
        assert isinstance(result, InvestorMandatesResponse)
        amount = result.mandates[0].amount
        assert amount is not None
        assert amount.value_millions == 300.0
        assert amount.currency == "USD"

    @respx.mock
    async def test_the_consultant_running_it_is_named(self) -> None:
        _mock([OPEN_SEARCH])
        client, _ = build_client()
        result = await get_mandates(investor_id=2504, client=client)
        assert isinstance(result, InvestorMandatesResponse)
        assert result.mandates[0].consultant == "A. Consultant"
        assert result.mandates[0].consultant_firm == "Consultant One"
        assert result.mandates[0].rfp_link == "https://example.invalid/rfp"


class TestNotes:
    @respx.mock
    async def test_the_latest_dated_note_is_surfaced(self) -> None:
        """Undated notes lose to dated ones rather than sorting first."""
        _mock([OPEN_SEARCH])
        client, _ = build_client()
        result = await get_mandates(investor_id=2504, client=client)
        assert isinstance(result, InvestorMandatesResponse)
        assert result.mandates[0].latest_note == "Shortlist drawn up."
        assert result.mandates[0].latest_note_date == "2026-07-15"

    @respx.mock
    async def test_notes_are_plain_text(self) -> None:
        mandate = {
            **OPEN_SEARCH,
            "note": (
                "<p>Approved a $25m commitment.&nbsp;"
                '<a href="https://example.invalid/recap">See the recap</a>.</p>'
            ),
            "notes": [
                {
                    "date": "2026-07-15",
                    "note": "<p>Shortlist drawn up.</p>",
                }
            ],
        }
        _mock([mandate])
        client, _ = build_client()
        result = await get_mandates(investor_id=2504, client=client)
        assert isinstance(result, InvestorMandatesResponse)
        assert result.mandates[0].note == "Approved a $25m commitment. See the recap."
        assert result.mandates[0].latest_note == "Shortlist drawn up."

    @respx.mock
    async def test_a_mandate_with_no_notes_omits_them(self) -> None:
        _mock([AWARDED])
        client, _ = build_client()
        result = await get_mandates(investor_id=2504, client=client)
        assert isinstance(result, InvestorMandatesResponse)
        assert result.mandates[0].latest_note is None


class TestScoping:
    @respx.mock
    async def test_asks_for_the_newest_first(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/mandates").mock(
            return_value=httpx.Response(200, json=page_body([], total=0))
        )
        respx.get(f"{BASE_URL}/v3/investors/2504").mock(
            return_value=httpx.Response(200, json=INVESTOR)
        )
        client, _ = build_client()
        _ = await get_mandates(investor_id=2504, client=client)
        query = sent_query(route)
        assert "investor_id=2504" in query
        assert "sort%5Bupdated_at%5D=desc" in query

    @respx.mock
    async def test_requests_the_selected_page(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/mandates").mock(
            return_value=httpx.Response(200, json=page_body([], total=75, page=3, size=10))
        )
        respx.get(f"{BASE_URL}/v3/investors/2504").mock(
            return_value=httpx.Response(200, json=INVESTOR)
        )
        client, _ = build_client()
        result = await get_mandates(investor_id=2504, page=3, limit=10, client=client)
        assert isinstance(result, InvestorMandatesResponse)
        assert result.page == 3
        assert result.has_more is True
        query = sent_query(route)
        assert "page=3" in query
        assert "page_size=10" in query

    @respx.mock
    async def test_an_ambiguous_name_asks_before_fetching(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors").mock(
            return_value=httpx.Response(
                200,
                json=page_body(
                    [{"id": 1, "name": "Virginia A"}, {"id": 2, "name": "Virginia B"}], total=20
                ),
            )
        )
        listing = respx.get(f"{BASE_URL}/v3/mandates").mock(
            return_value=httpx.Response(200, json=page_body([], total=0))
        )
        client, _ = build_client()
        result = await get_mandates(name="Virginia", client=client)
        assert isinstance(result, InvestorAmbiguousResponse)
        assert listing.call_count == 0
