import httpx
import pytest
import respx

from backstop_mcp.features.custom_fields import CustomFieldMatch
from backstop_mcp.features.org_people import (
    MAX_PEOPLE_SCAN_RECORDS,
    LocationFilter,
    SearchPeopleResolvedResponse,
)
from tests.features.org_people.conftest import make_search_people_query
from tests.helpers import (
    BASE_URL,
    contact_location,
    linked_to_locations,
    recorded_params,
    recorded_requests,
    resource,
    tool_client,
)

_FIELDS = frozenset({"id", "name", "email", "job_title", "company_name", "city", "country"})


def _page(
    *items: dict[str, object],
    total: int | None = None,
    included: tuple[dict[str, object], ...] = (),
) -> httpx.Response:
    body: dict[str, object] = {"data": list(items), "links": {"next": None}}
    if included:
        body["included"] = list(included)
    if total is not None:
        body["meta"] = {"totalResourceCount": total}
    return httpx.Response(200, json=body)


def _person(
    person_id: str,
    *,
    name: str,
    first_name: str | None = None,
    city: str | None = None,
    job_title: str | None = None,
    custom_fields: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    attributes: dict[str, object] = {}
    if first_name is not None:
        attributes["firstName"] = first_name
    if city is not None:
        attributes["city"] = city
    if job_title is not None:
        attributes["jobTitle"] = job_title
    if custom_fields is not None:
        attributes["regularCustomFieldValues"] = custom_fields
    return resource(person_id, "people", name, **attributes)


class TestSearchPeopleQuery:
    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_server_filters_and_keeps_memory_matches(self) -> None:
        base_url = f"{BASE_URL}/people-search-memory"
        route = respx.get(f"{base_url}/people").mock(
            return_value=_page(
                _person(
                    "1",
                    name="West, Ann",
                    first_name="Ann",
                    city="Wichita",
                    job_title="Director",
                    custom_fields=[
                        {"definitionId": "10", "name": "Registered", "value": "Yes"},
                        {"definitionId": "11", "name": "Registered", "value": "No"},
                        {"definitionId": "12", "name": "Region", "value": ["EMEA", "US"]},
                    ],
                ),
                _person(
                    "2",
                    name="West, Bea",
                    first_name="Ann",
                    city="London",
                    job_title="Director",
                    custom_fields=[
                        {"definitionId": "10", "name": "Registered", "value": "Yes"},
                        {"definitionId": "12", "name": "Region", "value": ["EMEA"]},
                    ],
                ),
                _person(
                    "3",
                    name="West, Cy",
                    first_name="Cy",
                    city="Wichita",
                    job_title="Director",
                    custom_fields=[
                        {"definitionId": "10", "name": "Registered", "value": "Yes"},
                    ],
                ),
                total=3,
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_people_query(client).run(
                name="West, Ann",
                last_name="West",
                other_id="OID",
                email_domain="example.com",
                first_name="ann",
                location_filter=LocationFilter(city="Wichita"),
                job_title="director",
                custom_fields=(
                    CustomFieldMatch(definition_id="10", values=("yes",)),
                    CustomFieldMatch(definition_id="12", values=("emea",)),
                ),
                fields=_FIELDS,
            )

        assert isinstance(result, SearchPeopleResolvedResponse)
        params = recorded_requests(route.calls)[0].url.params
        assert params["filter[name][eq]"] == "West, Ann"
        assert params["filter[lastName][like]"] == "West"
        assert params["filter[otherId][eq]"] == "OID"
        assert params["filter[emailDomains][eq]"] == "example.com"
        assert params["sort"] == "name"
        assert params["page[limit]"] == "500"
        wire_fields = params["fields[people]"]
        assert "regularCustomFieldValues" in wire_fields
        assert "emailDomains" not in wire_fields
        assert "filter[name][like]" not in params
        assert "filter[firstName][like]" not in params
        assert "filter[city]" not in params
        assert "filter[jobTitle]" not in params
        assert "filter[regularCustomFieldValues]" not in params
        assert [row.id for row in result.rows] == ["1"]
        assert result.rows[0].custom_field_values is not None
        published = {
            (item.definition_id, item.value) for item in result.rows[0].custom_field_values
        }
        assert published == {("10", "Yes"), ("11", "No"), ("12", "EMEA; US")}
        assert result.coverage.ceiling_hit is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_email_is_three_lookups_unioned_by_id(self) -> None:
        base_url = f"{BASE_URL}/people-search-email"

        def respond(request: httpx.Request) -> httpx.Response:
            params = request.url.params
            assert params["filter[lastName][like]"] == "West"
            if "filter[email][eq]" in params:
                assert params["filter[email][eq]"] == "a@example.com"
                return _page(_person("1", name="West, Ann"), total=1)
            if "filter[email2][eq]" in params:
                assert params["filter[email2][eq]"] == "a@example.com"
                return _page(_person("2", name="Alpha, Bob"), total=1)
            if "filter[email3][eq]" in params:
                assert params["filter[email3][eq]"] == "a@example.com"
                return _page(_person("1", name="West, Ann"), total=1)
            raise AssertionError(dict(params))

        route = respx.get(f"{base_url}/people").mock(side_effect=respond)

        async with tool_client(base_url) as client:
            result = await make_search_people_query(client).run(
                last_name="West",
                email="a@example.com",
                fields=_FIELDS,
            )

        assert len(route.calls) == 3
        assert [row.id for row in result.rows] == ["2", "1"]
        assert result.coverage.visible_count == 3
        assert result.coverage.rows_scanned == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_predicate_matches_any_of_its_values(self) -> None:
        base_url = f"{BASE_URL}/people-search-any-of"
        investor_status = {"definitionId": "900011", "name": "Tier"}
        status = {"definitionId": "900014", "name": "Status"}
        respx.get(f"{base_url}/people").mock(
            return_value=_page(
                _person(
                    "1",
                    name="Dialogue Tier",
                    custom_fields=[
                        {**investor_status, "value": "Tier 1"},
                        {**status, "value": "Stage A"},
                    ],
                ),
                _person(
                    "2",
                    name="Project Tier",
                    custom_fields=[
                        {**investor_status, "value": "Tier 1"},
                        {**status, "value": "Stage B"},
                    ],
                ),
                _person(
                    "3",
                    name="Dead Tier",
                    custom_fields=[
                        {**investor_status, "value": "Tier 1"},
                        {**status, "value": "Stage C"},
                    ],
                ),
                _person(
                    "4",
                    name="Client",
                    custom_fields=[
                        {**investor_status, "value": "Tier 2"},
                        {**status, "value": "Stage D"},
                    ],
                ),
                total=4,
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_people_query(client).run(
                custom_fields=(
                    CustomFieldMatch(definition_id="900011", values=("tier 1",)),
                    CustomFieldMatch(definition_id="900014", values=("Stage A", "Stage B")),
                ),
                fields=_FIELDS,
            )

        assert [row.id for row in result.rows] == ["1", "2"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_exclude_custom_fields_does_not_request_them(self) -> None:
        base_url = f"{BASE_URL}/people-search-exclude"
        route = respx.get(f"{base_url}/people").mock(
            return_value=_page(
                _person(
                    "1",
                    name="West, Ann",
                    custom_fields=[
                        {"definitionId": "900013", "name": "Relationship", "value": "Tier 1"}
                    ],
                ),
                total=1,
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_people_query(client).run(
                last_name="West",
                exclude_custom_fields=True,
                fields=_FIELDS,
            )

        params = recorded_requests(route.calls)[0].url.params
        assert "regularCustomFieldValues" not in params["fields[people]"]
        assert result.rows[0].custom_field_values is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_sorts_memory_matches_by_name(self) -> None:
        base_url = f"{BASE_URL}/people-search-sort"
        respx.get(f"{base_url}/people").mock(
            return_value=_page(
                _person("2", name="Zebra", city="Wichita"),
                _person("1", name="Alpha", city="Wichita"),
                total=2,
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_people_query(client).run(
                location_filter=LocationFilter(city="Wichita"),
                fields=_FIELDS,
            )

        assert [row.id for row in result.rows] == ["1", "2"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_memory_walk_reports_the_ceiling(self) -> None:
        base_url = f"{BASE_URL}/people-search-ceiling"
        items = [
            _person(str(index), name=f"Person {index}", city="Elsewhere")
            for index in range(MAX_PEOPLE_SCAN_RECORDS)
        ]
        respx.get(f"{base_url}/people").mock(
            return_value=_page(*items, total=MAX_PEOPLE_SCAN_RECORDS + 2_000)
        )

        async with tool_client(base_url) as client:
            result = await make_search_people_query(client).run(
                location_filter=LocationFilter(city="Wichita"),
                fields=_FIELDS,
            )

        assert result.rows == ()
        assert result.coverage.rows_scanned == MAX_PEOPLE_SCAN_RECORDS
        assert result.coverage.ceiling_hit is True
        assert result.coverage.truncated is True
        assert result.coverage.disclaimer is not None

    @pytest.mark.asyncio
    @respx.mock
    async def test_matches_any_address_and_publishes_them(self) -> None:
        base_url = f"{BASE_URL}/people-search-locations"
        london = contact_location(
            "l2",
            city="London",
            country="United Kingdom",
            countryCode="GB",
            address="10 New Burlington St",
            isPrimaryLocation=False,
        )
        boston = contact_location(
            "l1", city="Boston", country="United States", countryCode="US", isPrimaryLocation=True
        )
        route = respx.get(f"{base_url}/people").mock(
            return_value=_page(
                linked_to_locations(
                    resource("1", "people", "Doe, Jane", city="Boston", country="United States"),
                    boston,
                    london,
                ),
                linked_to_locations(
                    resource("2", "people", "Roe, Rick", city="Cambridge"),
                    contact_location("l3", city="Cambridge", isPrimaryLocation=True),
                ),
                resource("3", "people", "Poe, Pat"),
                total=3,
                included=(boston, london, contact_location("l3", city="Cambridge")),
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_people_query(client).run(
                location_filter=LocationFilter(city="London"),
                fields=frozenset({"name", "city", "locations"}),
            )

        assert recorded_requests(route.calls)[0].url.params["include"] == "contactLocations"
        assert [row.id for row in result.rows] == ["1"]
        row = result.rows[0]
        assert row.city == "Boston"
        assert row.locations is not None
        assert [(item.id, item.city, item.is_primary) for item in row.locations] == [
            ("l1", "Boston", True),
            ("l2", "London", False),
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_primary_only_ignores_other_addresses(self) -> None:
        base_url = f"{BASE_URL}/people-search-primary-only"
        boston = contact_location("l1", city="Boston", isPrimaryLocation=True)
        london = contact_location("l2", city="London", isPrimaryLocation=False)
        respx.get(f"{base_url}/people").mock(
            return_value=_page(
                linked_to_locations(
                    resource("1", "people", "Doe, Jane", city="Boston"), boston, london
                ),
                total=1,
                included=(boston, london),
            )
        )

        async with tool_client(base_url) as client:
            query = make_search_people_query(client)
            other_office = await query.run(
                location_filter=LocationFilter(city="London", primary_only=True), fields=_FIELDS
            )
            primary = await query.run(
                location_filter=LocationFilter(city="Boston", primary_only=True), fields=_FIELDS
            )

        assert other_office.rows == ()
        assert [row.id for row in primary.rows] == ["1"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_every_field_must_match_the_same_address(self) -> None:
        base_url = f"{BASE_URL}/people-search-same-address"
        boston = contact_location(
            "l1", city="Boston", country="United States", countryCode="US", isPrimaryLocation=True
        )
        london = contact_location(
            "l2", city="London", country="United Kingdom", countryCode="GB", isPrimaryLocation=False
        )
        respx.get(f"{base_url}/people").mock(
            return_value=_page(
                linked_to_locations(resource("1", "people", "Doe, Jane"), boston, london),
                total=1,
                included=(boston, london),
            )
        )

        async with tool_client(base_url) as client:
            query = make_search_people_query(client)
            split_across = await query.run(
                location_filter=LocationFilter(city="London", country="United States"),
                fields=_FIELDS,
            )
            by_name = await query.run(
                location_filter=LocationFilter(city="London", country="kingdom"), fields=_FIELDS
            )
            by_code = await query.run(
                location_filter=LocationFilter(city="London", country="gb"), fields=_FIELDS
            )

        assert split_across.rows == ()
        assert [row.id for row in by_name.rows] == ["1"]
        assert [row.id for row in by_code.rows] == ["1"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_email_lookups_share_the_side_loaded_addresses(self) -> None:
        base_url = f"{BASE_URL}/people-search-email-locations"
        london = contact_location("l2", city="London", isPrimaryLocation=False)
        respx.get(f"{base_url}/people").mock(
            return_value=_page(
                linked_to_locations(resource("1", "people", "Doe, Jane"), london),
                total=1,
                included=(london,),
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_people_query(client).run(
                email="jane@example.com",
                location_filter=LocationFilter(city="London"),
                fields=_FIELDS,
            )

        assert [row.id for row in result.rows] == ["1"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_nothing_for_the_fields_backstop_cannot_filter(self) -> None:
        base_url = f"{BASE_URL}/people-search-no-city"
        route = respx.get(f"{base_url}/people").mock(return_value=_page(total=0))

        async with tool_client(base_url) as client:
            await make_search_people_query(client).run(
                location_filter=LocationFilter(country="Finland", state="MA"), fields=_FIELDS
            )

        params = recorded_params(route)
        assert len(params) == 1
        assert not any(
            key.startswith("filter[contactLocations") for key, _ in params[0].multi_items()
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_the_city_and_street_address_exactly_as_passed(self) -> None:
        base_url = f"{BASE_URL}/people-search-exact-pass-through"
        london = contact_location(
            "l1", city="London", address="10 New Burlington St", isPrimaryLocation=True
        )
        route = respx.get(f"{base_url}/people").mock(
            return_value=_page(
                linked_to_locations(resource("1", "people", "Doe, Jane"), london),
                total=1,
                included=(london,),
            )
        )

        async with tool_client(base_url) as client:
            query = make_search_people_query(client)
            exact = await query.run(
                location_filter=LocationFilter(
                    city="London", street_address="10 New Burlington St"
                ),
                fields=_FIELDS,
            )
            lowercase = await query.run(
                location_filter=LocationFilter(city="london"), fields=_FIELDS
            )
            partial = await query.run(location_filter=LocationFilter(city="Lond"), fields=_FIELDS)

        sent = recorded_params(route)
        assert [params["filter[contactLocations.city][eq]"] for params in sent] == [
            "London",
            "london",
            "Lond",
        ]
        assert sent[0]["filter[contactLocations.address][eq]"] == "10 New Burlington St"
        assert "filter[contactLocations.address][eq]" not in sent[1]
        assert [row.id for row in exact.rows] == ["1"]
        assert lowercase.rows == ()
        assert partial.rows == ()

    @pytest.mark.asyncio
    @respx.mock
    async def test_the_location_filter_rides_on_every_email_lookup(self) -> None:
        base_url = f"{BASE_URL}/people-search-email-city"
        route = respx.get(f"{base_url}/people").mock(return_value=_page(total=0))

        async with tool_client(base_url) as client:
            await make_search_people_query(client).run(
                email="jane@example.com",
                location_filter=LocationFilter(city="London"),
                fields=_FIELDS,
            )

        params = recorded_params(route)
        assert len(params) == 3
        assert {item["filter[contactLocations.city][eq]"] for item in params} == {"London"}
