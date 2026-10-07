import httpx
import pytest
import respx

from backstop_mcp.features.custom_fields import CustomFieldMatch
from backstop_mcp.features.org_people import (
    MAX_ORGANIZATION_SCAN_RECORDS,
    SearchOrganizationsResolvedResponse,
)
from tests.features.org_people.conftest import make_search_organizations_query
from tests.helpers import BASE_URL, recorded_requests, resource, tool_client

_FIELDS = frozenset({"id", "name", "legal_name", "email", "city", "country"})


def _page(
    *items: dict[str, object],
    total: int | None = None,
) -> httpx.Response:
    body: dict[str, object] = {"data": list(items), "links": {"next": None}}
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
                    legal_name="Koch Holdings",
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
                    legal_name="Koch Holdings",
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
                name="Koch",
                email="a@example.com",
                other_id="OID",
                matching_domain="example.com",
                legal_name="holdings",
                city="wichita",
                ria=True,
                custom_fields=(
                    CustomFieldMatch(definition_id="10", values=("yes",)),
                    CustomFieldMatch(definition_id="12", values=("emea",)),
                ),
                fields=_FIELDS,
            )

        assert isinstance(result, SearchOrganizationsResolvedResponse)
        params = recorded_requests(route.calls)[0].url.params
        assert params["filter[name][like]"] == "Koch"
        assert params["filter[email][eq]"] == "a@example.com"
        assert params["filter[otherId][eq]"] == "OID"
        assert params["filter[matchingDomains][eq]"] == "example.com"
        assert params["sort"] == "name"
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
        investor_status = {"definitionId": "261621", "name": "Investor Status"}
        status = {"definitionId": "8646237", "name": "Status"}
        respx.get(f"{base_url}/organizations").mock(
            return_value=_page(
                _org(
                    "1",
                    name="Dialogue Prospect",
                    custom_fields=[
                        {**investor_status, "value": "Prospect"},
                        {**status, "value": "1 - Dialogue"},
                    ],
                ),
                _org(
                    "2",
                    name="Project Prospect",
                    custom_fields=[
                        {**investor_status, "value": "Prospect"},
                        {**status, "value": "2 - Project"},
                    ],
                ),
                _org(
                    "3",
                    name="Dead Prospect",
                    custom_fields=[
                        {**investor_status, "value": "Prospect"},
                        {**status, "value": "0 - Dead"},
                    ],
                ),
                _org(
                    "4",
                    name="Client",
                    custom_fields=[
                        {**investor_status, "value": "Current Investor"},
                        {**status, "value": "4 - Client"},
                    ],
                ),
                total=4,
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_organizations_query(client).run(
                custom_fields=(
                    CustomFieldMatch(definition_id="261621", values=("prospect",)),
                    CustomFieldMatch(
                        definition_id="8646237", values=("1 - Dialogue", "2 - Project")
                    ),
                ),
                fields=_FIELDS,
            )

        assert [row.id for row in result.rows] == ["1", "2"]
        assert result.rows[1].custom_field_values is not None
        assert {
            (item.definition_id, item.value) for item in result.rows[1].custom_field_values
        } == {
            ("261621", "Prospect"),
            ("8646237", "2 - Project"),
        }

    @pytest.mark.asyncio
    @respx.mock
    async def test_publishes_every_set_custom_field_without_filtering(self) -> None:
        base_url = f"{BASE_URL}/org-search-columns"
        route = respx.get(f"{base_url}/organizations").mock(
            return_value=_page(
                _org(
                    "1",
                    name="Helsinki Pension",
                    custom_fields=[
                        {"definitionId": "8646227", "name": "Grade", "value": "Focus"},
                        {
                            "definitionId": "261623",
                            "name": "Investor Type",
                            "value": "Public Pension",
                        },
                        {"definitionId": "99", "name": "Regions", "value": ["EMEA", "APAC"]},
                    ],
                ),
                _org("2", name="Helsinki Family Office", custom_fields=[]),
                total=2,
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_organizations_query(client).run(
                name="Helsinki",
                fields=_FIELDS,
            )

        params = recorded_requests(route.calls)[0].url.params
        assert "regularCustomFieldValues" in params["fields[organizations]"]
        assert [row.id for row in result.rows] == ["1", "2"]
        first = result.rows[0].custom_field_values
        assert first is not None
        assert [(item.definition_id, item.name, item.value) for item in first] == [
            ("8646227", "Grade", "Focus"),
            ("261623", "Investor Type", "Public Pension"),
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
                    name="Helsinki Pension",
                    custom_fields=[{"definitionId": "8646227", "name": "Grade", "value": "Focus"}],
                ),
                total=1,
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_organizations_query(client).run(
                name="Helsinki",
                exclude_custom_fields=True,
                fields=_FIELDS,
            )

        params = recorded_requests(route.calls)[0].url.params
        assert "regularCustomFieldValues" not in params["fields[organizations]"]
        assert result.rows[0].custom_field_values is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_sorts_memory_matches_by_name(self) -> None:
        base_url = f"{BASE_URL}/org-search-sort"
        respx.get(f"{base_url}/organizations").mock(
            return_value=_page(
                _org("2", name="Zebra", city="Wichita"),
                _org("1", name="Alpha", city="wichita"),
                total=2,
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_organizations_query(client).run(
                city="WICHITA",
                fields=_FIELDS,
            )

        assert [row.id for row in result.rows] == ["1", "2"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_server_only_filter_returns_every_match(self) -> None:
        base_url = f"{BASE_URL}/org-search-all"
        route = respx.get(f"{base_url}/organizations").mock(
            return_value=_page(
                *(
                    _org(str(index), name=f"Koch {index:03}", city="Wichita")
                    for index in range(150)
                ),
                total=150,
            )
        )

        async with tool_client(base_url) as client:
            result = await make_search_organizations_query(client).run(
                name="Koch",
                fields=_FIELDS,
            )

        params = recorded_requests(route.calls)[0].url.params
        assert "regularCustomFieldValues" in params["fields[organizations]"]
        assert len(result.rows) == 150
        assert result.coverage.truncated is False
        assert result.coverage.visible_count == 150

    @pytest.mark.asyncio
    @respx.mock
    async def test_memory_walk_reports_the_ceiling(self) -> None:
        base_url = f"{BASE_URL}/org-search-ceiling"
        items = [
            _org(str(index), name=f"Org {index}", city="Elsewhere")
            for index in range(MAX_ORGANIZATION_SCAN_RECORDS)
        ]
        respx.get(f"{base_url}/organizations").mock(
            return_value=_page(*items, total=MAX_ORGANIZATION_SCAN_RECORDS + 2_000)
        )

        async with tool_client(base_url) as client:
            result = await make_search_organizations_query(client).run(
                city="Wichita",
                fields=_FIELDS,
            )

        assert result.rows == ()
        assert result.coverage.rows_scanned == MAX_ORGANIZATION_SCAN_RECORDS
        assert result.coverage.ceiling_hit is True
        assert result.coverage.truncated is True
        assert result.coverage.disclaimer is not None
