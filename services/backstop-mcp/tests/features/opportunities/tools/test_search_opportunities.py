from typing import cast, get_args

import httpx
import pytest
import respx
from fastmcp.server.dependencies import without_injected_parameters
from pydantic import TypeAdapter, ValidationError
from pydantic.fields import FieldInfo

from backstop_mcp.features.opportunities import SearchOpportunitiesResolvedResponse
from backstop_mcp.features.opportunities.tools.search_opportunities import search_opportunities
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
    **attrs: object,
) -> dict[str, object]:
    relationships: dict[str, object] = {
        "stage": {"data": {"id": stage_id, "type": "opportunity-stages"}},
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
        resource("42482", "opportunity-stages", name="IDD"),
        resource(
            "c1",
            "contacts",
            name="Koch",
            country="United States of America",
            state="KS",
            city="Wichita",
            contactDescription="x" * 200,
        ),
        resource("p1", "products", name="CATS Select"),
    ]


class TestSearchOpportunities:
    def test_is_registered_and_says_the_filter_takes_a_login(self) -> None:
        assert search_opportunities in TOOLS
        doc = search_opportunities.__doc__ or ""
        assert "login" in doc
        assert "list_system_users" in doc
        assert "get_opportunities" in doc
        assert "get_opportunities_by_ids" in doc
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
    async def test_pins_login_filter_and_sparse_contact_fields(self) -> None:
        base_url = tenant("so-filter")
        opportunities = respx.get(f"{base_url}/opportunities").mock(
            return_value=_page(
                _deal("1", name="Koch - CATS Select", stage_id="42482"),
                included=_included(),
                total=1,
            )
        )
        _stub_supporting_collections(base_url)

        async with tool_client(base_url) as client:
            result = tool_model(
                await search_opportunities(
                    representative="blazarus",
                    search_opportunities_query=make_search_opportunities_query(client),
                ),
                SearchOpportunitiesResolvedResponse,
            )

        assert opportunities.call_count == 1
        params = recorded_requests(opportunities.calls)[0].url.params
        assert params["filter[representative.name][eq]"] == "blazarus"
        assert params["include"] == "investor,product,stage"
        assert params["fields[contacts]"] == "name,country,state,city"
        assert "weightedValue" in params["fields[opportunities]"]
        assert "weightedAllocatedValue" in params["fields[opportunities]"]
        assert params["page[limit]"] == "500"
        assert params["page[offset]"] == "0"
        assert "filter[isOpen]" not in params
        assert "filter[stage.name]" not in params
        assert "filter[product.name]" not in params
        payload = tool_payload(result)
        rows = [object_dict(item) for item in object_list(payload["rows"])]
        assert rows[0]["id"] == "1"
        assert rows[0]["stage"] == "IDD"
        investor = object_dict(rows[0]["investor"])
        assert investor["name"] == "Koch"
        assert investor["country"] == "United States of America"
        assert "contactDescription" not in investor
        product = object_dict(rows[0]["product"])
        assert product["name"] == "CATS Select"

    @pytest.mark.asyncio
    @respx.mock
    async def test_stage_and_is_open_are_client_side(self) -> None:
        base_url = tenant("so-client")
        respx.get(f"{base_url}/opportunities").mock(
            return_value=_page(
                _deal("1", name="open-idd", stage_id="42482", is_open=True),
                _deal("2", name="closed-idd", stage_id="42482", is_open=False),
                _deal("3", name="open-other", stage_id="42478", is_open=True),
                included=_included() + [resource("42478", "opportunity-stages", name="Prospect")],
                total=3,
            )
        )
        _stub_supporting_collections(base_url)

        async with tool_client(base_url) as client:
            result = tool_model(
                await search_opportunities(
                    is_open=True,
                    stage="IDD",
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
                included=_included() + [resource("42478", "opportunity-stages", name="Prospect")],
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
        assert buckets[0]["label"] == "IDD"
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
                _deal("1", name="Koch - CATS Select", stage_id="42482"),
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
        assert [item["name"] for item in rows] == ["Koch - CATS Select", "Other"]
        assert set(rows[0]) == {"id", "name"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_catalog_failure_keeps_the_rows(self) -> None:
        base_url = tenant("so-catalog-down")
        respx.get(f"{base_url}/opportunities").mock(
            return_value=_page(
                _deal("1", name="Koch - CATS Select", stage_id="42482"),
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


class TestSearchOpportunitiesInput:
    def test_rejects_unknown_mode(self) -> None:
        with pytest.raises(ValidationError):
            _INPUT.validate_python({"mode": "nope"})
