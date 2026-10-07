import httpx
import pytest
import respx
from pydantic import ValidationError

from backstop_mcp.features.org_people import LocationFilter
from tests.features.org_people.conftest import make_search_organizations_query
from tests.helpers import BASE_URL, contact_location, linked_to_locations, resource, tool_client


class TestLocationFilter:
    def test_rejects_a_filter_with_no_text_field(self) -> None:
        with pytest.raises(ValidationError, match="needs a city"):
            LocationFilter(primary_only=True)

    def test_blank_text_counts_as_unset(self) -> None:
        with pytest.raises(ValidationError, match="needs a city"):
            LocationFilter(city="   ", country="")

    def test_strips_text(self) -> None:
        assert LocationFilter(city=" London ").city == "London"


async def _matches(location_filter: LocationFilter, **stored: object) -> bool:
    """Whether one organization with one location holding `stored` survives the filter."""
    base_url = f"{BASE_URL}/location-match"
    office = contact_location("l1", isPrimaryLocation=True, **stored)
    respx.get(f"{base_url}/organizations").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [linked_to_locations(resource("1", "organizations", "Contoso"), office)],
                "included": [office],
                "links": {"next": None},
                "meta": {"totalResourceCount": 1},
            },
        )
    )
    async with tool_client(base_url) as client:
        result = await make_search_organizations_query(client).run(
            location_filter=location_filter, fields=frozenset({"id"}), result_size=100
        )
    return [row.id for row in result.rows] == ["1"]


class TestLocationMatching:
    @pytest.mark.asyncio
    @respx.mock
    @pytest.mark.parametrize(
        ("stored", "wanted", "expected"),
        [
            ("Kansas", "kansas", True),
            ("KS", "ks", True),
            ("Arkansas", "Kansas", False),
            ("KS", "K", False),
        ],
    )
    async def test_state_is_the_whole_value_in_any_case(
        self, stored: str, wanted: str, expected: bool
    ) -> None:
        assert await _matches(LocationFilter(state=wanted), state=stored) is expected

    @pytest.mark.asyncio
    @respx.mock
    @pytest.mark.parametrize(
        ("stored", "wanted", "expected"),
        [
            ("United States of America", "United States", True),
            ("United States Of America", "united states of america", True),
            ("United Kingdom", "kingdom", True),
            ("Nigeria", "Niger", False),
            ("Niger", "Niger", True),
            ("Guinea-Bissau", "Guinea", True),
            ("Papua New Guinea", "New Guin", False),
            ("United States", "United.States", False),
        ],
    )
    async def test_country_name_is_literal_whole_words_in_any_case(
        self, stored: str, wanted: str, expected: bool
    ) -> None:
        assert await _matches(LocationFilter(country=wanted), country=stored) is expected

    @pytest.mark.asyncio
    @respx.mock
    @pytest.mark.parametrize(("wanted", "expected"), [("us", True), ("un", False)])
    async def test_two_letter_country_is_an_exact_iso_code(
        self, wanted: str, expected: bool
    ) -> None:
        assert (
            await _matches(
                LocationFilter(country=wanted), country="United States", countryCode="US"
            )
            is expected
        )
