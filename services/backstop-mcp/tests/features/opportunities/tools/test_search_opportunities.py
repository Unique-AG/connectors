from typing import cast, get_args

import httpx
import pytest
import respx
from fastmcp.server.dependencies import without_injected_parameters
from pydantic import TypeAdapter, ValidationError
from pydantic.fields import FieldInfo

from backstop_mcp.features.opportunities import SearchOpportunitiesResolvedResponse
from backstop_mcp.features.opportunities.tools.search_opportunities import (
    OpportunityCustomFieldFilter,
    search_opportunities,
)
from backstop_mcp.models import CoercedId
from backstop_mcp.server.tools import TOOLS
from tests.features.opportunities.conftest import VOCABULARY, make_search_opportunities_query
from tests.helpers import (
    BASE_URL,
    recorded_requests,
    resource,
    tool_client,
)
from tests.server.tools.helpers import object_dict, object_list, tool_model, tool_payload

_INPUT: TypeAdapter[object] = TypeAdapter(without_injected_parameters(search_opportunities))


def tenant(name: str) -> str:
    return f"{BASE_URL}/{name}"


def _page(
    *items: dict[str, object],
    included: list[dict[str, object]] | None = None,
    total: int | None = None,
    next_url: str | None = None,
) -> httpx.Response:
    body: dict[str, object] = {
        "data": list(items),
        "included": included or [],
        "links": {"next": next_url},
    }
    if total is not None:
        body["meta"] = {"totalResourceCount": total}
    return httpx.Response(200, json=body)


def _stages_page() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                resource(
                    stage.id,
                    "opportunity-stages",
                    name=stage.name,
                    sortOrder=stage.sort_order,
                    closed=stage.closed,
                )
                for stage in VOCABULARY.values()
            ],
            "links": {"next": None},
        },
    )


def _deal(
    deal_id: str,
    *,
    name: str,
    stage_id: str,
    is_open: bool = True,
    investor_id: str | None = "c1",
    product_id: str | None = "p1",
    representative_id: str | None = None,
    **attrs: object,
) -> dict[str, object]:
    relationships: dict[str, object] = {
        "stage": {"data": {"id": stage_id, "type": "opportunity-stages"}},
    }
    if representative_id is not None:
        relationships["representative"] = {
            "data": {"id": representative_id, "type": "system-users"}
        }
    if investor_id is not None:
        relationships["investor"] = {"data": {"id": investor_id, "type": "contacts"}}
    if product_id is not None:
        relationships["product"] = {"data": {"id": product_id, "type": "products"}}
    return {
        "id": deal_id,
        "type": "opportunities",
        "attributes": {"name": name, "isOpen": is_open, **attrs},
        "relationships": relationships,
    }


_EMPTY_DEFINITIONS: dict[str, object] = {"data": [], "links": {"next": None}}


def _stub_supporting_collections(base_url: str) -> None:
    respx.get(f"{base_url}/opportunity-stages").mock(return_value=_stages_page())
    respx.get(f"{base_url}/custom-field-definitions").mock(
        return_value=httpx.Response(200, json=_EMPTY_DEFINITIONS)
    )


def _included() -> list[dict[str, object]]:
    return [
        resource("42482", "opportunity-stages", name="Stage B"),
        resource(
            "c1",
            "contacts",
            name="Contoso",
            country="United States of America",
            state="KS",
            city="Wichita",
            contactDescription="x" * 200,
            specificResource={
                "resourceType": "organizations",
                "resourceId": "c1",
                "resourceLink": "https://example.test/organizations/c1",
                "restricted": False,
            },
        ),
        resource("p1", "products", name="Harbor Select"),
    ]


class TestSearchOpportunities:
    def test_is_registered_and_says_the_filter_takes_a_login(self) -> None:
        assert search_opportunities in TOOLS
        doc = search_opportunities.__doc__ or ""
        assert "login" in doc
        assert "list_system_users" in doc
        assert "get_opportunities" in doc
        assert "get_opportunities_by_ids" in doc
        assert "custom_fields" in doc
        assert "list_custom_fields" in doc
        assert "exact option" not in doc
        annotations = cast("dict[str, object]", search_opportunities.__annotations__)
        field_info = next(
            item
            for item in cast("tuple[object, ...]", get_args(annotations["representative"]))
            if isinstance(item, FieldInfo)
        )
        assert field_info.description is not None
        assert "login" in field_info.description.casefold()

    @pytest.mark.asyncio
    @respx.mock
    async def test_pins_sparse_fields_and_both_representative_includes(self) -> None:
        base_url = tenant("so-filter")
        opportunities = respx.get(f"{base_url}/opportunities").mock(
            return_value=_page(
                _deal("1", name="Contoso - Harbor Select", stage_id="42482"),
                included=_included(),
                total=1,
            )
        )
        _stub_supporting_collections(base_url)

        async with tool_client(base_url) as client:
            result = tool_model(
                await search_opportunities(
                    search_opportunities_query=make_search_opportunities_query(client),
                ),
                SearchOpportunitiesResolvedResponse,
            )

        assert opportunities.call_count == 1
        params = recorded_requests(opportunities.calls)[0].url.params
        assert "filter[representative.name][eq]" not in params
        assert params["include"] == "investor,investor.representative,representative,product,stage"
        # Without `representative` here Backstop drops the organization's linkage.
        assert params["fields[contacts]"] == (
            "name,country,state,city,specificResource,representative"
        )
        assert params["fields[system-users]"] == "userName"
        assert "representative" in params["fields[opportunities]"].split(",")
        assert "weightedValue" in params["fields[opportunities]"]
        assert "weightedAllocatedValue" in params["fields[opportunities]"]
        assert "regularCustomFieldValues" in params["fields[opportunities]"]
        assert params["page[limit]"] == "500"
        assert params["page[offset]"] == "0"
        assert "filter[isOpen]" not in params
        assert "filter[stage.name]" not in params
        assert "filter[product.name]" not in params
        payload = tool_payload(result)
        rows = [object_dict(item) for item in object_list(payload["rows"])]
        assert rows[0]["id"] == "1"
        assert rows[0]["stage"] == "Stage B"
        investor = object_dict(rows[0]["investor"])
        assert investor["name"] == "Contoso"
        assert investor["country"] == "United States of America"
        assert investor["search_type"] == "organizations"
        assert "contactDescription" not in investor
        assert "specificResource" not in investor
        product = object_dict(rows[0]["product"])
        assert product["name"] == "Harbor Select"

    @pytest.mark.asyncio
    @respx.mock
    async def test_representative_is_the_investor_organization_book(self) -> None:
        base_url = tenant("so-representative")
        opportunities = respx.get(f"{base_url}/opportunities").mock(
            return_value=_page(
                _deal("1", name="Deal and org", stage_id="42482", representative_id="u1"),
                _deal("2", name="Org only", stage_id="42482"),
                _deal(
                    "3",
                    name="Deal only",
                    stage_id="42482",
                    investor_id="c2",
                    representative_id="u1",
                ),
                included=[
                    resource("42482", "opportunity-stages", name="Stage B"),
                    {
                        **resource("c1", "contacts", name="Contoso"),
                        "relationships": {
                            "representative": {"data": {"id": "u1", "type": "system-users"}}
                        },
                    },
                    {
                        **resource("c2", "contacts", name="Fabrikam"),
                        "relationships": {
                            "representative": {"data": {"id": "u2", "type": "system-users"}}
                        },
                    },
                    resource("u1", "system-users", userName="jdoe"),
                    resource("u2", "system-users", userName="asmith"),
                ],
                total=3,
            )
        )
        _stub_supporting_collections(base_url)

        async with tool_client(base_url) as client:
            result = tool_model(
                await search_opportunities(
                    representative="Jdoe",
                    fields=["name", "representative"],
                    search_opportunities_query=make_search_opportunities_query(client),
                ),
                SearchOpportunitiesResolvedResponse,
            )

        params = recorded_requests(opportunities.calls)[0].url.params
        assert "filter[representative.name][eq]" not in params
        rows = [object_dict(item) for item in object_list(tool_payload(result)["rows"])]
        assert [row["id"] for row in rows] == ["1", "2"]
        assert [row["investor_representative"] for row in rows] == ["jdoe", "jdoe"]
        assert rows[0]["representative"] == "jdoe"
        assert "representative" not in rows[1]

    @pytest.mark.asyncio
    @respx.mock
    async def test_stage_and_is_open_are_client_side(self) -> None:
        base_url = tenant("so-client")
        respx.get(f"{base_url}/opportunities").mock(
            return_value=_page(
                _deal("1", name="open-idd", stage_id="42482", is_open=True),
                _deal("2", name="closed-idd", stage_id="42482", is_open=False),
                _deal("3", name="open-other", stage_id="42478", is_open=True),
                included=_included() + [resource("42478", "opportunity-stages", name="Stage A")],
                total=3,
            )
        )
        _stub_supporting_collections(base_url)

        async with tool_client(base_url) as client:
            result = tool_model(
                await search_opportunities(
                    is_open=True,
                    stage="Stage B",
                    search_opportunities_query=make_search_opportunities_query(client),
                ),
                SearchOpportunitiesResolvedResponse,
            )

        rows = [object_dict(item) for item in object_list(tool_payload(result)["rows"])]
        assert [item["id"] for item in rows] == ["1"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_aggregate_by_stage_does_not_return_row_bodies(self) -> None:
        base_url = tenant("so-agg")
        respx.get(f"{base_url}/opportunities").mock(
            return_value=_page(
                _deal("1", name="a", stage_id="42482"),
                _deal("2", name="b", stage_id="42482"),
                _deal("3", name="c", stage_id="42478"),
                included=_included() + [resource("42478", "opportunity-stages", name="Stage A")],
                total=3,
            )
        )
        _stub_supporting_collections(base_url)

        async with tool_client(base_url) as client:
            result = tool_model(
                await search_opportunities(
                    mode="aggregate",
                    group_by="stage",
                    search_opportunities_query=make_search_opportunities_query(client),
                ),
                SearchOpportunitiesResolvedResponse,
            )

        payload = tool_payload(result)
        assert object_list(payload["rows"]) == []
        buckets = [object_dict(item) for item in object_list(payload["aggregates"])]
        assert buckets[0]["label"] == "Stage B"
        assert buckets[0]["count"] == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_unreadable_amount_is_treated_as_absent(self) -> None:
        """Lenient page schema: a bad scalar is omitted, not a dropped row."""
        base_url = tenant("so-drop")
        respx.get(f"{base_url}/opportunities").mock(
            return_value=_page(
                _deal("bad", name="x", stage_id="42482", requestedAmount="nope"),
                _deal("1", name="ok", stage_id="42482"),
                included=_included(),
                total=2,
            )
        )
        _stub_supporting_collections(base_url)

        async with tool_client(base_url) as client:
            result = tool_model(
                await search_opportunities(
                    fields=["name", "requested_amount"],
                    search_opportunities_query=make_search_opportunities_query(client),
                ),
                SearchOpportunitiesResolvedResponse,
            )

        rows = [object_dict(item) for item in object_list(tool_payload(result)["rows"])]
        assert [item["id"] for item in rows] == ["bad", "1"]
        assert "requested_amount" not in rows[0]
        assert result.coverage.rows_dropped == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_second_page_is_requested_in_parallel_by_offset(self) -> None:
        base_url = tenant("so-pages")
        first = _deal("1", name="a", stage_id="42482")
        second = _deal("2", name="b", stage_id="42482")
        route = respx.get(f"{base_url}/opportunities").mock(
            side_effect=[
                _page(
                    first,
                    included=_included(),
                    total=2,
                    next_url=f"{base_url}/opportunities?page[offset]=1",
                ),
                _page(second, included=_included(), total=2),
            ]
        )
        _stub_supporting_collections(base_url)

        async with tool_client(base_url) as client:
            result = tool_model(
                await search_opportunities(
                    search_opportunities_query=make_search_opportunities_query(client),
                ),
                SearchOpportunitiesResolvedResponse,
            )

        assert route.call_count == 2
        params = [request.url.params for request in recorded_requests(route.calls)]
        assert params[0]["page[offset]"] == "0"
        assert params[1]["page[offset]"] == "1"
        assert params[1]["page[limit]"] == "1"
        rows = [object_dict(item) for item in object_list(tool_payload(result)["rows"])]
        assert {item["id"] for item in rows} == {"1", "2"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_id_is_always_on_the_row_even_when_fields_omit_it(self) -> None:
        base_url = tenant("so-id")
        respx.get(f"{base_url}/opportunities").mock(
            return_value=_page(
                _deal("1", name="Contoso - Harbor Select", stage_id="42482"),
                _deal("2", name="Other", stage_id="42482"),
                included=_included(),
                total=2,
            )
        )
        _stub_supporting_collections(base_url)

        async with tool_client(base_url) as client:
            result = tool_model(
                await search_opportunities(
                    fields=["name"],
                    search_opportunities_query=make_search_opportunities_query(client),
                ),
                SearchOpportunitiesResolvedResponse,
            )

        rows = [object_dict(item) for item in object_list(tool_payload(result)["rows"])]
        assert [item["id"] for item in rows] == ["1", "2"]
        assert [item["name"] for item in rows] == ["Contoso - Harbor Select", "Other"]
        assert set(rows[0]) == {"id", "name"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_url_is_off_by_default_and_arrives_when_selected(self) -> None:
        base_url = tenant("so-url")
        respx.get(f"{base_url}/opportunities").mock(
            return_value=_page(
                _deal("1", name="Contoso - Harbor Select", stage_id="42482"),
                included=_included(),
                total=1,
            )
        )
        _stub_supporting_collections(base_url)

        async with tool_client(base_url) as client:
            query = make_search_opportunities_query(
                client, ui_base_url="https://tenant.example.test"
            )
            default_result = tool_model(
                await search_opportunities(search_opportunities_query=query),
                SearchOpportunitiesResolvedResponse,
            )
            selected_result = tool_model(
                await search_opportunities(
                    fields=["name", "url"], search_opportunities_query=query
                ),
                SearchOpportunitiesResolvedResponse,
            )

        default_rows = object_list(tool_payload(default_result)["rows"])
        assert "url" not in object_dict(default_rows[0])
        selected_rows = object_list(tool_payload(selected_result)["rows"])
        assert object_dict(selected_rows[0])["url"] == (
            "https://tenant.example.test/backstop/crm/Opportunity.action?display=&entityId=1"
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_catalog_failure_keeps_the_rows(self) -> None:
        base_url = tenant("so-catalog-down")
        respx.get(f"{base_url}/opportunities").mock(
            return_value=_page(
                _deal("1", name="Contoso - Harbor Select", stage_id="42482"),
                included=_included(),
                total=1,
            )
        )
        respx.get(f"{base_url}/opportunity-stages").mock(return_value=_stages_page())
        respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(500, json={"errors": [{"detail": "down"}]})
        )

        async with tool_client(base_url) as client:
            result = tool_model(
                await search_opportunities(
                    search_opportunities_query=make_search_opportunities_query(client),
                ),
                SearchOpportunitiesResolvedResponse,
            )

        rows = [object_dict(item) for item in object_list(tool_payload(result)["rows"])]
        assert [item["id"] for item in rows] == ["1"]
        assert result.custom_fields_unavailable is True


def _product_page() -> httpx.Response:
    return _page(
        _deal("on", name="north vehicle", stage_id="42482", product_id="p-on"),
        _deal("off", name="second vehicle", stage_id="42482", product_id="p-off"),
        _deal("none", name="no product", stage_id="42482", product_id=None),
        included=[
            resource("42482", "opportunity-stages", name="Stage B"),
            resource("c1", "contacts", name="Contoso"),
            resource(
                "p-on",
                "products",
                name="Northwind Harbor Fund (Alpha)",
                configuration={"productShortName": "NWON"},
            ),
            resource(
                "p-off",
                "products",
                name="Northwind Harbor Fund (Beta)",
                configuration={"productShortName": "NWOF"},
            ),
        ],
        total=3,
    )


class TestSearchOpportunitiesProductFilter:
    @pytest.mark.asyncio
    @respx.mock
    @pytest.mark.parametrize(
        ("product", "expected_ids"),
        [
            pytest.param(["NWON"], ["on"], id="short-name-exact"),
            pytest.param([" nwon "], ["on"], id="short-name-case-and-space-insensitive"),
            pytest.param(["NWO"], [], id="short-name-is-not-a-prefix-match"),
            pytest.param(["harbor"], ["on", "off"], id="display-name-substring"),
            pytest.param(["beta"], ["off"], id="display-name-substring-narrows"),
            pytest.param(["NWON", "NWOF"], ["on", "off"], id="several-products-are-or"),
            pytest.param(["unrelated"], [], id="no-match"),
        ],
    )
    async def test_matches_short_name_exactly_or_display_name_substring(
        self, product: list[str], expected_ids: list[str]
    ) -> None:
        base_url = tenant("so-product")
        route = respx.get(f"{base_url}/opportunities").mock(return_value=_product_page())
        _stub_supporting_collections(base_url)

        async with tool_client(base_url) as client:
            result = tool_model(
                await search_opportunities(
                    product=product,
                    search_opportunities_query=make_search_opportunities_query(client),
                ),
                SearchOpportunitiesResolvedResponse,
            )

        params = recorded_requests(route.calls)[0].url.params
        assert params["fields[products]"] == "name,configuration"
        assert "filter[product.name]" not in params
        rows = [object_dict(item) for item in object_list(tool_payload(result)["rows"])]
        assert [item["id"] for item in rows] == expected_ids

    @pytest.mark.asyncio
    @respx.mock
    async def test_short_name_is_read_from_configuration(self) -> None:
        base_url = tenant("so-product-short")
        respx.get(f"{base_url}/opportunities").mock(return_value=_product_page())
        _stub_supporting_collections(base_url)

        async with tool_client(base_url) as client:
            result = tool_model(
                await search_opportunities(
                    product=["NWON"],
                    search_opportunities_query=make_search_opportunities_query(client),
                ),
                SearchOpportunitiesResolvedResponse,
            )

        rows = [object_dict(item) for item in object_list(tool_payload(result)["rows"])]
        product = object_dict(rows[0]["product"])
        assert product["id"] == "p-on"
        assert product["short_name"] == "NWON"


def _custom_fields(*rows: tuple[str, str, str]) -> list[dict[str, object]]:
    return [
        {"definitionId": definition_id, "name": name, "value": value}
        for definition_id, name, value in rows
    ]


class TestSearchOpportunitiesCustomFields:
    @pytest.mark.asyncio
    @respx.mock
    async def test_filters_the_exact_stored_option_and_publishes_columns(self) -> None:
        base_url = tenant("so-cf")
        route = respx.get(f"{base_url}/opportunities").mock(
            return_value=_page(
                _deal(
                    "convert",
                    name="Contoso - Alpha",
                    stage_id="42478",
                    regularCustomFieldValues=_custom_fields(
                        ("900001", "Flavor", "Alpha"),
                        ("900002", "Deal Kind", "Kind A"),
                    ),
                ),
                _deal(
                    "named-only",
                    name="Northwind - Alpha",
                    stage_id="42478",
                    regularCustomFieldValues=_custom_fields(
                        ("900001", "Flavor", "Beta"),
                    ),
                ),
                _deal(
                    "other-case",
                    name="Quiet book",
                    stage_id="42478",
                    regularCustomFieldValues=_custom_fields(
                        ("900001", "Flavor", "alpha"),
                    ),
                ),
                included=_included() + [resource("42478", "opportunity-stages", name="Stage A")],
                total=3,
            )
        )
        _stub_supporting_collections(base_url)

        async with tool_client(base_url) as client:
            result = tool_model(
                await search_opportunities(
                    is_open=True,
                    custom_fields=[
                        OpportunityCustomFieldFilter(definition_id="900001", values=["Alpha"])
                    ],
                    fields=["name", "stage", "investor"],
                    search_opportunities_query=make_search_opportunities_query(client),
                ),
                SearchOpportunitiesResolvedResponse,
            )

        params = recorded_requests(route.calls)[0].url.params
        assert "regularCustomFieldValues" in params["fields[opportunities]"]
        assert "filter[regularCustomFieldValues]" not in params
        rows = [object_dict(item) for item in object_list(tool_payload(result)["rows"])]
        assert [item["id"] for item in rows] == ["convert", "other-case"]
        published = [object_dict(item) for item in object_list(rows[0]["custom_field_values"])]
        assert published == [
            {"definition_id": "900001", "name": "Flavor", "value": "Alpha"},
            {"definition_id": "900002", "name": "Deal Kind", "value": "Kind A"},
        ]
        other = [object_dict(item) for item in object_list(rows[1]["custom_field_values"])]
        assert other == [{"definition_id": "900001", "name": "Flavor", "value": "alpha"}]

    @pytest.mark.asyncio
    @respx.mock
    async def test_exclude_custom_fields_does_not_request_them(self) -> None:
        base_url = tenant("so-cf-exclude")
        route = respx.get(f"{base_url}/opportunities").mock(
            return_value=_page(
                _deal(
                    "convert",
                    name="Contoso - Alpha",
                    stage_id="42478",
                    regularCustomFieldValues=_custom_fields(("900001", "Flavor", "Alpha")),
                ),
                included=_included() + [resource("42478", "opportunity-stages", name="Stage A")],
                total=1,
            )
        )
        _stub_supporting_collections(base_url)

        async with tool_client(base_url) as client:
            result = tool_model(
                await search_opportunities(
                    exclude_custom_fields=True,
                    search_opportunities_query=make_search_opportunities_query(client),
                ),
                SearchOpportunitiesResolvedResponse,
            )

        params = recorded_requests(route.calls)[0].url.params
        assert "regularCustomFieldValues" not in params["fields[opportunities]"]
        rows = [object_dict(item) for item in object_list(tool_payload(result)["rows"])]
        assert "custom_field_values" not in rows[0]

    @pytest.mark.asyncio
    async def test_exclude_custom_fields_is_refused_with_a_custom_field_filter(self) -> None:
        async with tool_client(tenant("so-cf-refused")) as client:
            with pytest.raises(ValueError, match="exclude_custom_fields"):
                await search_opportunities(
                    custom_fields=[OpportunityCustomFieldFilter(definition_id="1", values=["Yes"])],
                    exclude_custom_fields=True,
                    search_opportunities_query=make_search_opportunities_query(client),
                )

    @pytest.mark.asyncio
    @respx.mock
    async def test_predicates_and_together(self) -> None:
        base_url = tenant("so-cf-and")
        respx.get(f"{base_url}/opportunities").mock(
            return_value=_page(
                _deal(
                    "both",
                    name="Fabrikam",
                    stage_id="42482",
                    regularCustomFieldValues=_custom_fields(
                        ("900001", "Flavor", "Alpha"),
                        ("900002", "Deal Kind", "Kind B"),
                    ),
                ),
                _deal(
                    "product-only",
                    name="Contoso Pension",
                    stage_id="42482",
                    regularCustomFieldValues=_custom_fields(
                        ("900001", "Flavor", "Alpha"),
                        ("900002", "Deal Kind", "Kind A"),
                    ),
                ),
                included=_included(),
                total=2,
            )
        )
        _stub_supporting_collections(base_url)

        async with tool_client(base_url) as client:
            result = tool_model(
                await search_opportunities(
                    custom_fields=[
                        OpportunityCustomFieldFilter(definition_id="900001", values=["Alpha"]),
                        OpportunityCustomFieldFilter(definition_id="900002", values=["Kind B"]),
                    ],
                    search_opportunities_query=make_search_opportunities_query(client),
                ),
                SearchOpportunitiesResolvedResponse,
            )

        rows = [object_dict(item) for item in object_list(tool_payload(result)["rows"])]
        assert [item["id"] for item in rows] == ["both"]


class TestSearchOpportunitiesInput:
    def test_custom_field_ids_accept_json_numbers(self) -> None:
        parsed = OpportunityCustomFieldFilter.model_validate(
            {"definition_id": 900001, "values": ["Alpha"]}
        )
        assert parsed.definition_id == "900001"
        assert TypeAdapter(list[CoercedId]).validate_python([900002]) == ["900002"]

    def test_product_must_be_a_list(self) -> None:
        with pytest.raises(ValidationError):
            _INPUT.validate_python({"product": "NWON"})

    def test_rejects_unknown_mode(self) -> None:
        with pytest.raises(ValidationError):
            _INPUT.validate_python({"mode": "nope"})
