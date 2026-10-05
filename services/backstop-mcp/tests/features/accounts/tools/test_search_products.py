from collections.abc import Awaitable, Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp.decorators import get_fastmcp_meta
from fastmcp.tools.function_tool import FunctionTool, ToolMeta
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.accounts import ProductResolvedResponse
from backstop_mcp.features.accounts.tools.search_products import (
    ProductCustomFieldFilter,
    search_products,
)
from backstop_mcp.features.ui_links import BuildEntityLinkUtil
from backstop_mcp.models import CoercedId
from backstop_mcp.server.tools import TOOLS
from tests.features.accounts.conftest import make_search_products_query
from tests.helpers import (
    BASE_URL,
    custom_fields_service,
    recorded_requests,
    resource,
    tool_client,
)
from tests.server.tools.helpers import object_dict, object_list, tool_model, tool_payload

_PRODUCT_ID = "1653647"
_NO_UI_LINKS = BuildEntityLinkUtil(ui_base_url=None)


def tenant(name: str) -> str:
    return f"{BASE_URL}/{name}"


def _product(
    product_id: str,
    *,
    name: str,
    short_name: str,
    values: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    attributes: dict[str, object] = {
        "name": name,
        "configuration": {"productShortName": short_name},
    }
    if values is not None:
        attributes["regularCustomFieldValues"] = list(values)
    return {"id": product_id, "type": "products", "attributes": attributes}


def _strategy_value() -> list[dict[str, object]]:
    return [{"definitionId": "501", "value": "Alpha"}]


def _definition() -> dict[str, object]:
    return resource(
        "501",
        "custom-field-definitions",
        name="Flavor",
        entityType="ProductBean",
        fieldType="select",
        tabName="Product",
        groupName="Product",
        groupId=9,
        layoutName="Product Layout",
    )


def _definitions_route(base_url: str) -> respx.Route:
    return respx.get(f"{base_url}/custom-field-definitions").mock(
        return_value=httpx.Response(200, json={"data": [_definition()], "links": {"next": None}})
    )


def _call(
    client: BackstopClient,
    *,
    name: str | None = None,
    product_ids: Sequence[str] = (),
    custom_fields: list[ProductCustomFieldFilter] | None = None,
    custom_field_names: Sequence[str] = (),
) -> Awaitable[ProductResolvedResponse]:
    return search_products(
        name=name,
        product_ids=product_ids,
        modified_since=None,
        product_type=None,
        is_onshore=None,
        custom_fields=custom_fields,
        custom_field_names=custom_field_names,
        custom_fields_service=custom_fields_service(client),
        search_products_query=make_search_products_query(client),
        build_entity_link_util=_NO_UI_LINKS,
    )


class TestSearchProducts:
    def test_is_registered_and_states_the_matching_rules(self) -> None:
        assert search_products in TOOLS
        doc = search_products.__doc__ or ""
        assert "AND" in doc
        assert "OR" in doc
        assert "never picks a product for the user" in doc
        assert "ask which they want" in doc
        assert "get_product_investors" in doc

    def test_parameter_descriptions_state_how_they_combine(self) -> None:
        meta = get_fastmcp_meta(search_products)
        assert isinstance(meta, ToolMeta)
        schema = object_dict(
            cast("object", FunctionTool.from_function(search_products, metadata=meta).parameters)
        )
        properties = object_dict(schema["properties"])
        name = str(object_dict(properties["name"])["description"])
        ids = str(object_dict(properties["product_ids"])["description"])
        assert "substring" in name
        assert "whole short name" in name
        assert "OR" in ids
        assert "AND with every other filter" in ids

    def test_product_ids_accept_json_numbers(self) -> None:
        ids = TypeAdapter(Sequence[CoercedId])

        assert ids.validate_python([1653647, " 2 "]) == ["1653647", "2"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_filters_returns_every_product_with_its_attributes(self) -> None:
        base_url = tenant("sp-cat")
        products = respx.get(f"{base_url}/products").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        _product(
                            _PRODUCT_ID,
                            name="Northwind Dispersion Fund",
                            short_name="NDSP",
                            values=_strategy_value(),
                        ),
                        _product("2", name="Northwind Tail Fund", short_name="NTLF"),
                    ],
                    "links": {"next": None},
                },
            )
        )
        _definitions_route(base_url)

        async with tool_client(base_url) as client:
            result = tool_model(
                await _call(client, custom_field_names=["Flavor"]), ProductResolvedResponse
            )

        assert products.call_count == 1
        assert "fields" not in recorded_requests(products.calls)[0].url.params
        rows = [object_dict(item) for item in object_list(tool_payload(result)["products"])]
        assert [row["id"] for row in rows] == [_PRODUCT_ID, "2"]
        assert rows[0]["short_name"] == "NDSP"
        fields = [object_dict(item) for item in object_list(rows[0]["custom_field_values"])]
        assert fields[0]["name"] == "Flavor"
        assert fields[0]["value"] == "Alpha"

    @pytest.mark.asyncio
    @respx.mock
    async def test_several_matches_come_back_together_without_elicitation(self) -> None:
        base_url = tenant("sp-many")
        index = respx.get(f"{base_url}/products").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        _product("1", name="Northwind Global (US), LP", short_name="CGUP"),
                        _product("2", name="Northwind Global Two Ltd", short_name="CGOL"),
                    ],
                    "links": {"next": None},
                },
            )
        )
        _definitions_route(base_url)

        async with tool_client(base_url) as client:
            result = tool_model(await _call(client, name="Global"), ProductResolvedResponse)

        assert [row.id for row in result.products] == ["1", "2"]
        assert recorded_requests(index.calls)[0].url.params["filter[name][like]"] == "Global"

    @pytest.mark.asyncio
    @respx.mock
    async def test_filters_and_together_and_a_miss_is_an_empty_list(self) -> None:
        base_url = tenant("sp-and")
        respx.get(f"{base_url}/products").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        _product(
                            "1",
                            name="Northwind Dispersion Fund",
                            short_name="NDSP",
                            values=_strategy_value(),
                        ),
                        _product("2", name="Northwind Tail Fund", short_name="NTLF"),
                    ],
                    "links": {"next": None},
                },
            )
        )
        _definitions_route(base_url)
        alpha = ProductCustomFieldFilter(definition_id="501", values=["alpha", "Beta"])
        gamma = ProductCustomFieldFilter(definition_id="501", values=["Gamma"])

        async with tool_client(base_url) as client:
            hit = tool_model(
                await _call(client, product_ids=["1", "2"], custom_fields=[alpha]),
                ProductResolvedResponse,
            )
            miss = tool_model(
                await _call(client, product_ids=["1", "2"], custom_fields=[alpha, gamma]),
                ProductResolvedResponse,
            )

        assert [row.id for row in hit.products] == ["1"]
        assert miss.products == ()
        assert miss.status == "resolved"
