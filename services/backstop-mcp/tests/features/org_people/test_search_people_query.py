import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from backstop_mcp.features.custom_fields import CustomFieldMatch
from backstop_mcp.features.org_people import (
    LocationFilter,
    SearchPeopleResolvedResponse,
)
from tests.features.data_hygiene.helpers import (
    EMPLOYEE_TYPE,
    FORMER_TYPE,
    person_org,
    relationship_types,
)
from tests.features.org_people.conftest import make_search_people_query, serve_pages
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
_RESULT_SIZE = 100


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


def _employed(person: dict[str, object], *relationship_ids: str) -> dict[str, object]:
    return person | {
        "relationships": {
            "entityRelationships": {
                "data": [
                    {"type": "entity-relationships", "id": relationship_id}
                    for relationship_id in relationship_ids
                ]
            }
        }
    }


_EMPLOYMENT_INCLUDED = (
    person_org("er1", source_id="1", dest_id="o1"),
    person_org("er2", source_id="1", dest_id="o2"),
    person_org("er3", source_id="2", dest_id="o1"),
    person_org("er4", source_id="2", dest_id="o3", type_id=FORMER_TYPE),
    *relationship_types(EMPLOYEE_TYPE, FORMER_TYPE),
)


class TestSearchPeopleEmployments:
    @pytest.mark.asyncio
    @respx.mock
    async def test_min_current_organizations_keeps_people_under_several(self) -> None:
        base_url = f"{BASE_URL}/people-search-multi-org"
        route = respx.get(f"{base_url}/people").mock(
            return_value=_page(
                _employed(_person("1", name="Two, Current"), "er1", "er2"),
                _employed(_person("2", name="One, Current"), "er3", "er4"),
                total=2,
                included=_EMPLOYMENT_INCLUDED,
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_people_query(client).run(
                min_current_organizations=2, result_size=_RESULT_SIZE, fields=_FIELDS
            )

        params = recorded_requests(route.calls)[0].url.params
        assert params["include"] == (
            "contactLocations,entityRelationships,entityRelationships.entityRelationshipType"
        )
        assert [row.id for row in result.rows] == ["1"]
        employments = result.rows[0].employments or ()
        assert sorted((link.organization_id, link.status) for link in employments) == [
            ("o1", "current"),
            ("o2", "current"),
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_employments_field_lists_current_and_former_without_filtering(
        self,
    ) -> None:
        base_url = f"{BASE_URL}/people-search-employments"
        respx.get(f"{base_url}/people").mock(
            return_value=_page(
                _employed(_person("1", name="Two, Current"), "er1", "er2"),
                _employed(_person("2", name="One, Current"), "er3", "er4"),
                total=2,
                included=_EMPLOYMENT_INCLUDED,
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_people_query(client).run(
                last_name="Current", result_size=_RESULT_SIZE, fields=_FIELDS | {"employments"}
            )

        by_id = {row.id: row.employments or () for row in result.rows}
        assert sorted((link.organization_id, link.status) for link in by_id["2"]) == [
            ("o1", "current"),
            ("o3", "former"),
        ]
        assert len(by_id["1"]) == 2


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
                result_size=_RESULT_SIZE,
                fields=_FIELDS,
            )

        assert isinstance(result, SearchPeopleResolvedResponse)
        params = recorded_requests(route.calls)[0].url.params
        assert params["filter[name][eq]"] == "West, Ann"
        assert params["filter[lastName][like]"] == "West"
        assert params["filter[otherId][eq]"] == "OID"
        assert params["filter[emailDomains][eq]"] == "example.com"
        assert params["sort"] == "id"
        assert params["include"] == "contactLocations"
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
    async def test_email_matches_any_of_the_three_fields_in_memory(self) -> None:
        base_url = f"{BASE_URL}/people-search-email"
        route = respx.get(f"{base_url}/people").mock(
            return_value=_page(
                resource("1", "people", "West, Ann", email="A@Example.com"),
                resource("2", "people", "West, Bob", email="b@example.com", email2="a@example.com"),
                resource("3", "people", "West, Cy", email3="a@example.com"),
                resource("4", "people", "West, Di", email="aa@example.com"),
                total=4,
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_people_query(client).run(
                last_name="West",
                email="a@example.com",
                result_size=_RESULT_SIZE,
                fields=_FIELDS,
            )

        params = recorded_params(route)
        assert len(params) == 1
        assert params[0]["filter[lastName][like]"] == "West"
        assert not any(key.startswith("filter[email") for key, _ in params[0].multi_items())
        assert [row.id for row in result.rows] == ["1", "2", "3"]
        assert result.coverage.visible_count == 4
        assert result.continuation is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_an_email_search_pages_with_a_cursor(self) -> None:
        base_url = f"{BASE_URL}/people-search-email-paged"
        items = [
            resource(str(index), "people", f"West, {index}", email="a@example.com")
            for index in range(3)
        ]
        respx.get(f"{base_url}/people").mock(side_effect=serve_pages(items))

        async with tool_client(base_url) as client:
            query = make_search_people_query(client)
            first = await query.run(email="a@example.com", result_size=2, fields=_FIELDS)
            assert first.continuation is not None
            second = await query.run(
                email="a@example.com",
                result_size=2,
                fields=_FIELDS,
                cursor=first.continuation.cursor,
            )

        assert [row.id for row in first.rows] == ["0", "1"]
        assert [row.id for row in second.rows] == ["2"]
        assert second.continuation is None

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
                result_size=_RESULT_SIZE,
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
                result_size=_RESULT_SIZE,
                fields=_FIELDS,
            )

        params = recorded_requests(route.calls)[0].url.params
        assert "regularCustomFieldValues" not in params["fields[people]"]
        assert result.rows[0].custom_field_values is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_keeps_the_server_id_order(self) -> None:
        base_url = f"{BASE_URL}/people-search-order"
        route = respx.get(f"{base_url}/people").mock(
            return_value=_page(
                _person("1", name="Zebra", city="Wichita"),
                _person("2", name="Alpha", city="Wichita"),
                total=2,
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_people_query(client).run(
                location_filter=LocationFilter(city="Wichita"),
                result_size=_RESULT_SIZE,
                fields=_FIELDS,
            )

        assert recorded_params(route)[0]["sort"] == "id"
        assert [row.id for row in result.rows] == ["1", "2"]
        assert result.continuation is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_full_page_hands_back_a_cursor_that_resumes_without_repeats(self) -> None:
        base_url = f"{BASE_URL}/people-search-pages"
        items = [
            _person(str(index), name=f"West, {index}", job_title="Director" if index % 2 else None)
            for index in range(1_200)
        ]
        respx.get(f"{base_url}/people").mock(side_effect=serve_pages(items))

        async with tool_client(base_url) as client:
            query = make_search_people_query(client)
            first = await query.run(
                last_name="West", job_title="director", result_size=250, fields=_FIELDS
            )
            assert first.continuation is not None
            second = await query.run(
                last_name="West",
                job_title="director",
                result_size=250,
                fields=_FIELDS,
                cursor=first.continuation.cursor,
            )
            assert second.continuation is not None
            third = await query.run(
                last_name="West",
                job_title="director",
                result_size=250,
                fields=_FIELDS,
                cursor=second.continuation.cursor,
            )

        assert third.continuation is None
        returned = [row.id for page in (first, second, third) for row in page.rows]
        assert returned == [str(index) for index in range(1, 1_200, 2)]
        assert [len(page.rows) for page in (first, second, third)] == [250, 250, 100]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_sparse_filter_reads_to_the_end_in_one_call(self) -> None:
        base_url = f"{BASE_URL}/people-search-sparse"
        total = 30_600
        items = [
            _person(
                str(index),
                name=f"Person {index}",
                job_title="CIO" if index == total - 50 else None,
            )
            for index in range(total)
        ]
        respx.get(f"{base_url}/people").mock(side_effect=serve_pages(items))

        async with tool_client(base_url) as client:
            result = await make_search_people_query(client).run(
                job_title="cio", result_size=_RESULT_SIZE, fields=_FIELDS
            )

        assert [row.id for row in result.rows] == [str(total - 50)]
        assert result.continuation is None
        assert result.coverage.rows_scanned == total
        assert result.coverage.truncated is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_cursor_from_other_arguments_is_rejected(self) -> None:
        base_url = f"{BASE_URL}/people-search-cursor-mismatch"
        items = [_person(str(index), name=f"West, {index}") for index in range(3)]
        respx.get(f"{base_url}/people").mock(side_effect=serve_pages(items))

        async with tool_client(base_url) as client:
            query = make_search_people_query(client)
            first = await query.run(last_name="West", result_size=2, fields=_FIELDS)
            assert first.continuation is not None
            with pytest.raises(ToolError, match="different search"):
                await query.run(
                    last_name="Weston",
                    result_size=2,
                    fields=_FIELDS,
                    cursor=first.continuation.cursor,
                )

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
                result_size=_RESULT_SIZE,
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
                location_filter=LocationFilter(city="London", primary_only=True),
                result_size=_RESULT_SIZE,
                fields=_FIELDS,
            )
            primary = await query.run(
                location_filter=LocationFilter(city="Boston", primary_only=True),
                result_size=_RESULT_SIZE,
                fields=_FIELDS,
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
                result_size=_RESULT_SIZE,
                fields=_FIELDS,
            )
            by_name = await query.run(
                location_filter=LocationFilter(city="London", country="kingdom"),
                result_size=_RESULT_SIZE,
                fields=_FIELDS,
            )
            by_code = await query.run(
                location_filter=LocationFilter(city="London", country="gb"),
                result_size=_RESULT_SIZE,
                fields=_FIELDS,
            )

        assert split_across.rows == ()
        assert [row.id for row in by_name.rows] == ["1"]
        assert [row.id for row in by_code.rows] == ["1"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_two_letter_country_is_an_exact_code_not_a_substring(self) -> None:
        base_url = f"{BASE_URL}/people-search-iso-country"
        sydney = contact_location(
            "l1", city="Sydney", country="Australia", countryCode="AU", isPrimaryLocation=True
        )
        boston = contact_location(
            "l2", city="Boston", country="United States", countryCode="US", isPrimaryLocation=True
        )
        respx.get(f"{base_url}/people").mock(
            return_value=_page(
                linked_to_locations(resource("1", "people", "Doe, Jane"), sydney),
                linked_to_locations(resource("2", "people", "Roe, Rich"), boston),
                total=2,
                included=(sydney, boston),
            )
        )

        async with tool_client(base_url) as client:
            found = await make_search_people_query(client).run(
                location_filter=LocationFilter(country="US"),
                result_size=_RESULT_SIZE,
                fields=_FIELDS,
            )

        assert [row.id for row in found.rows] == ["2"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_email_and_location_filter_combine(self) -> None:
        base_url = f"{BASE_URL}/people-search-email-locations"
        london = contact_location("l2", city="London", isPrimaryLocation=False)
        respx.get(f"{base_url}/people").mock(
            return_value=_page(
                linked_to_locations(
                    resource("1", "people", "Doe, Jane", email="jane@example.com"), london
                ),
                total=1,
                included=(london,),
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_people_query(client).run(
                email="jane@example.com",
                location_filter=LocationFilter(city="London"),
                result_size=_RESULT_SIZE,
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
                location_filter=LocationFilter(country="Finland", state="MA"),
                result_size=_RESULT_SIZE,
                fields=_FIELDS,
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
                result_size=_RESULT_SIZE,
                fields=_FIELDS,
            )
            lowercase = await query.run(
                location_filter=LocationFilter(city="london"),
                result_size=_RESULT_SIZE,
                fields=_FIELDS,
            )
            partial = await query.run(
                location_filter=LocationFilter(city="Lond"),
                result_size=_RESULT_SIZE,
                fields=_FIELDS,
            )

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
