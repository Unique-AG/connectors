import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from backstop_mcp.features.custom_fields import CustomFieldMatch
from backstop_mcp.features.org_people import (
    LocationFilter,
    SearchOrganizationsResolvedResponse,
)
from tests.features.org_people.conftest import make_search_organizations_query, serve_pages
from tests.helpers import (
    BASE_URL,
    contact_location,
    linked_to_locations,
    recorded_params,
    recorded_requests,
    resource,
    tool_client,
)

_FIELDS = frozenset({"id", "name", "legal_name", "email", "city", "country"})
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


def _org(
    org_id: str,
    *,
    name: str,
    city: str | None = None,
    legal_name: str | None = None,
    ria: bool | None = None,
    custom_fields: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    attributes: dict[str, object] = {}
    if city is not None:
        attributes["city"] = city
    if legal_name is not None:
        attributes["legalName"] = legal_name
    if ria is not None:
        attributes["ria"] = ria
    if custom_fields is not None:
        attributes["regularCustomFieldValues"] = custom_fields
    return resource(org_id, "organizations", name, **attributes)


class TestSearchOrganizationsQuery:
    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_server_filters_and_keeps_memory_matches(self) -> None:
        base_url = f"{BASE_URL}/org-search-memory"
        route = respx.get(f"{base_url}/organizations").mock(
            return_value=_page(
                _org(
                    "1",
                    name="Zebra",
                    city="Wichita",
                    legal_name="Contoso Holdings",
                    ria=True,
                    custom_fields=[
                        {"definitionId": "10", "name": "Registered", "value": "Yes"},
                        {"definitionId": "11", "name": "Registered", "value": "No"},
                        {"definitionId": "12", "name": "Region", "value": ["EMEA", "US"]},
                    ],
                ),
                _org(
                    "2",
                    name="Alpha",
                    city="Wichita",
                    legal_name="Contoso Holdings",
                    ria=True,
                    custom_fields=[
                        {"definitionId": "11", "name": "Registered", "value": "Yes"},
                    ],
                ),
                _org(
                    "3",
                    name="London",
                    city="London",
                    legal_name="Other",
                    ria=False,
                    custom_fields=[
                        {"definitionId": "10", "name": "Registered", "value": "Yes"},
                    ],
                ),
                total=3,
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_organizations_query(client).run(
                name="Contoso",
                email="a@example.com",
                other_id="OID",
                matching_domain="example.com",
                legal_name="holdings",
                location_filter=LocationFilter(city="Wichita"),
                ria=True,
                custom_fields=(
                    CustomFieldMatch(definition_id="10", values=("yes",)),
                    CustomFieldMatch(definition_id="12", values=("emea",)),
                ),
                result_size=_RESULT_SIZE,
                fields=_FIELDS,
            )

        assert isinstance(result, SearchOrganizationsResolvedResponse)
        params = recorded_requests(route.calls)[0].url.params
        assert params["filter[name][like]"] == "Contoso"
        assert params["filter[email][eq]"] == "a@example.com"
        assert params["filter[otherId][eq]"] == "OID"
        assert params["filter[matchingDomains][eq]"] == "example.com"
        assert params["sort"] == "id"
        assert params["page[limit]"] == "500"
        assert "regularCustomFieldValues" in params["fields[organizations]"]
        assert "filter[city]" not in params
        assert "filter[legalName]" not in params
        assert "filter[ria]" not in params
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
    async def test_a_predicate_matches_any_of_its_values(self) -> None:
        base_url = f"{BASE_URL}/org-search-any-of"
        investor_status = {"definitionId": "900011", "name": "Tier"}
        status = {"definitionId": "900014", "name": "Status"}
        respx.get(f"{base_url}/organizations").mock(
            return_value=_page(
                _org(
                    "1",
                    name="Dialogue Tier",
                    custom_fields=[
                        {**investor_status, "value": "Tier 1"},
                        {**status, "value": "Stage A"},
                    ],
                ),
                _org(
                    "2",
                    name="Project Tier",
                    custom_fields=[
                        {**investor_status, "value": "Tier 1"},
                        {**status, "value": "Stage B"},
                    ],
                ),
                _org(
                    "3",
                    name="Dead Tier",
                    custom_fields=[
                        {**investor_status, "value": "Tier 1"},
                        {**status, "value": "Stage C"},
                    ],
                ),
                _org(
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
            result = await make_search_organizations_query(client).run(
                custom_fields=(
                    CustomFieldMatch(definition_id="900011", values=("tier 1",)),
                    CustomFieldMatch(definition_id="900014", values=("Stage A", "Stage B")),
                ),
                result_size=_RESULT_SIZE,
                fields=_FIELDS,
            )

        assert [row.id for row in result.rows] == ["1", "2"]
        assert result.rows[1].custom_field_values is not None
        assert {
            (item.definition_id, item.value) for item in result.rows[1].custom_field_values
        } == {
            ("900011", "Tier 1"),
            ("900014", "Stage B"),
        }

    @pytest.mark.asyncio
    @respx.mock
    async def test_publishes_every_set_custom_field_without_filtering(self) -> None:
        base_url = f"{BASE_URL}/org-search-columns"
        route = respx.get(f"{base_url}/organizations").mock(
            return_value=_page(
                _org(
                    "1",
                    name="Contoso Pension",
                    custom_fields=[
                        {"definitionId": "900013", "name": "Relationship", "value": "Tier 1"},
                        {
                            "definitionId": "900012",
                            "name": "Kind",
                            "value": "Kind A",
                        },
                        {"definitionId": "99", "name": "Regions", "value": ["EMEA", "APAC"]},
                    ],
                ),
                _org("2", name="Northwind Family Office", custom_fields=[]),
                total=2,
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_organizations_query(client).run(
                name="Contoso",
                result_size=_RESULT_SIZE,
                fields=_FIELDS,
            )

        params = recorded_requests(route.calls)[0].url.params
        assert "regularCustomFieldValues" in params["fields[organizations]"]
        assert [row.id for row in result.rows] == ["1", "2"]
        first = result.rows[0].custom_field_values
        assert first is not None
        assert [(item.definition_id, item.name, item.value) for item in first] == [
            ("900013", "Relationship", "Tier 1"),
            ("900012", "Kind", "Kind A"),
            ("99", "Regions", "EMEA; APAC"),
        ]
        assert result.rows[1].custom_field_values is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_exclude_custom_fields_does_not_request_them(self) -> None:
        base_url = f"{BASE_URL}/org-search-exclude"
        route = respx.get(f"{base_url}/organizations").mock(
            return_value=_page(
                _org(
                    "1",
                    name="Contoso Pension",
                    custom_fields=[
                        {"definitionId": "900013", "name": "Relationship", "value": "Tier 1"}
                    ],
                ),
                total=1,
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_organizations_query(client).run(
                name="Contoso",
                exclude_custom_fields=True,
                result_size=_RESULT_SIZE,
                fields=_FIELDS,
            )

        params = recorded_requests(route.calls)[0].url.params
        assert "regularCustomFieldValues" not in params["fields[organizations]"]
        assert result.rows[0].custom_field_values is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_keeps_the_server_id_order(self) -> None:
        base_url = f"{BASE_URL}/org-search-order"
        route = respx.get(f"{base_url}/organizations").mock(
            return_value=_page(
                _org("1", name="Zebra", city="Wichita"),
                _org("2", name="Alpha", city="Wichita"),
                total=2,
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_organizations_query(client).run(
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
        base_url = f"{BASE_URL}/org-search-pages"
        items = [_org(str(index), name=f"Contoso {index:04}") for index in range(700)]
        route = respx.get(f"{base_url}/organizations").mock(side_effect=serve_pages(items))

        async with tool_client(base_url) as client:
            query = make_search_organizations_query(client)
            pages = [await query.run(name="Contoso", result_size=300, fields=_FIELDS)]
            while (cursor := pages[-1].continuation) is not None:
                pages.append(
                    await query.run(
                        name="Contoso", result_size=300, fields=_FIELDS, cursor=cursor.cursor
                    )
                )

        assert [len(page.rows) for page in pages] == [300, 300, 100]
        assert [row.id for page in pages for row in page.rows] == [str(i) for i in range(700)]
        first = pages[0].continuation
        assert first is not None
        assert "300 rows" in first.message
        assert pages[0].coverage.visible_count == 700
        assert pages[0].coverage.truncated is False
        assert [params["page[offset]"] for params in recorded_params(route)] == [
            "0",
            "0",
            "500",
            "500",
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_sparse_filter_reads_to_the_end_in_one_call(self) -> None:
        base_url = f"{BASE_URL}/org-search-sparse"
        total = 10_600
        items = [
            resource(
                str(index),
                "organizations",
                f"Org {index}",
                state="Kansas" if index == total - 50 else "Ohio",
            )
            for index in range(total)
        ]
        respx.get(f"{base_url}/organizations").mock(side_effect=serve_pages(items))

        async with tool_client(base_url) as client:
            result = await make_search_organizations_query(client).run(
                location_filter=LocationFilter(state="Kansas"),
                result_size=_RESULT_SIZE,
                fields=_FIELDS,
            )

        assert [row.id for row in result.rows] == [str(total - 50)]
        assert result.continuation is None
        assert result.coverage.rows_scanned == total
        assert result.coverage.truncated is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_cursor_from_other_arguments_is_rejected(self) -> None:
        base_url = f"{BASE_URL}/org-search-cursor-mismatch"
        items = [_org(str(index), name=f"Contoso {index}") for index in range(3)]
        respx.get(f"{base_url}/organizations").mock(side_effect=serve_pages(items))

        async with tool_client(base_url) as client:
            query = make_search_organizations_query(client)
            first = await query.run(name="Contoso", result_size=2, fields=_FIELDS)
            assert first.continuation is not None
            with pytest.raises(ToolError, match="different search"):
                await query.run(
                    name="Northwind",
                    result_size=2,
                    fields=_FIELDS,
                    cursor=first.continuation.cursor,
                )
            with pytest.raises(ToolError, match="different search"):
                await query.run(
                    name="Contoso",
                    result_size=2,
                    fields=_FIELDS | {"website"},
                    cursor=first.continuation.cursor,
                )
            with pytest.raises(ToolError, match="not one this server issued"):
                await query.run(name="Contoso", result_size=2, fields=_FIELDS, cursor="garbage")

    @pytest.mark.asyncio
    @respx.mock
    async def test_matches_any_office_and_publishes_them(self) -> None:
        base_url = f"{BASE_URL}/org-search-locations"
        boston = contact_location(
            "l1", city="Boston", country="United States", countryCode="US", isPrimaryLocation=True
        )
        london = contact_location(
            "l2",
            city="London",
            country="United Kingdom",
            countryCode="GB",
            address="10 New Burlington St",
            isPrimaryLocation=False,
        )
        route = respx.get(f"{base_url}/organizations").mock(
            return_value=_page(
                linked_to_locations(
                    resource("1", "organizations", "Boston Pension", city="Boston"), boston, london
                ),
                linked_to_locations(
                    resource("2", "organizations", "Cambridge Endowment", city="Cambridge"),
                    contact_location("l3", city="Cambridge", isPrimaryLocation=True),
                ),
                resource("3", "organizations", "No Location"),
                total=3,
                included=(boston, london, contact_location("l3", city="Cambridge")),
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_organizations_query(client).run(
                location_filter=LocationFilter(city="London"),
                result_size=_RESULT_SIZE,
                fields=frozenset({"name", "city", "locations"}),
            )

        assert recorded_requests(route.calls)[0].url.params["include"] == "contactLocations"
        assert [row.id for row in result.rows] == ["1"]
        row = result.rows[0]
        assert row.city == "Boston"
        assert row.locations is not None
        assert [(item.id, item.city, item.address, item.is_primary) for item in row.locations] == [
            ("l1", "Boston", None, True),
            ("l2", "London", "10 New Burlington St", False),
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_primary_only_ignores_other_offices(self) -> None:
        base_url = f"{BASE_URL}/org-search-primary-only"
        boston = contact_location("l1", city="Boston", isPrimaryLocation=True)
        london = contact_location("l2", city="London", isPrimaryLocation=False)
        respx.get(f"{base_url}/organizations").mock(
            return_value=_page(
                linked_to_locations(
                    resource("1", "organizations", "Boston Pension", city="Boston"),
                    boston,
                    london,
                ),
                total=1,
                included=(boston, london),
            )
        )

        async with tool_client(base_url) as client:
            query = make_search_organizations_query(client)
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
    async def test_every_field_must_match_the_same_office(self) -> None:
        base_url = f"{BASE_URL}/org-search-same-office"
        boston = contact_location(
            "l1", city="Boston", country="United States", countryCode="US", isPrimaryLocation=True
        )
        london = contact_location(
            "l2", city="London", country="United Kingdom", countryCode="GB", isPrimaryLocation=False
        )
        respx.get(f"{base_url}/organizations").mock(
            return_value=_page(
                linked_to_locations(
                    resource("1", "organizations", "Boston Pension"), boston, london
                ),
                total=1,
                included=(boston, london),
            )
        )

        async with tool_client(base_url) as client:
            query = make_search_organizations_query(client)
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
    async def test_falls_back_to_the_inlined_primary_location(self) -> None:
        base_url = f"{BASE_URL}/org-search-inlined-primary"
        respx.get(f"{base_url}/organizations").mock(
            return_value=_page(
                resource(
                    "1",
                    "organizations",
                    "Boston Pension",
                    city="Boston",
                    state="MA",
                    postalCode="02110",
                    streetAddress="1 Federal St",
                    locationTitle="Business",
                ),
                total=1,
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_organizations_query(client).run(
                location_filter=LocationFilter(
                    state="ma",
                    postal_code="021",
                    street_address="1 Federal St",
                    location_title="busin",
                ),
                result_size=_RESULT_SIZE,
                fields=frozenset({"name", "locations"}),
            )

        assert [row.id for row in result.rows] == ["1"]
        assert result.rows[0].locations is not None
        assert result.rows[0].locations[0].address == "1 Federal St"
        assert result.rows[0].locations[0].is_primary is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_nothing_for_the_fields_backstop_cannot_filter(self) -> None:
        base_url = f"{BASE_URL}/org-search-no-city"
        route = respx.get(f"{base_url}/organizations").mock(return_value=_page(total=0))

        async with tool_client(base_url) as client:
            await make_search_organizations_query(client).run(
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
        base_url = f"{BASE_URL}/org-search-exact-pass-through"
        london = contact_location(
            "l1", city="London", address="10 New Burlington St", isPrimaryLocation=True
        )
        route = respx.get(f"{base_url}/organizations").mock(
            return_value=_page(
                linked_to_locations(resource("1", "organizations", "Abrdn"), london),
                total=1,
                included=(london,),
            )
        )

        async with tool_client(base_url) as client:
            query = make_search_organizations_query(client)
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
