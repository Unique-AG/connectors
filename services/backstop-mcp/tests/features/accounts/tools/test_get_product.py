from collections.abc import Mapping, Sequence

import httpx
import pytest
import respx

from backstop_mcp.features.accounts import ProductResolvedResponse
from backstop_mcp.features.accounts.tools.get_product import get_product
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.server.tools import TOOLS
from tests.features.accounts.conftest import make_get_product_query
from tests.features.party_resolver.helpers import ctx_never_elicit
from tests.helpers import (
    BASE_URL,
    custom_fields_service,
    recorded_requests,
    resource,
    tool_client,
)
from tests.server.tools.helpers import object_dict, object_list, tool_model, tool_payload

_PRODUCT_ID = "1653647"


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
    return [{"definitionId": "501", "value": "Convertible Arbitrage"}]


def _definition() -> dict[str, object]:
    return resource(
        "501",
        "custom-field-definitions",
        name="Strategy",
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


class TestGetProduct:
    def test_is_registered(self) -> None:
        assert get_product in TOOLS
        doc = get_product.__doc__ or ""
        assert "Strategy" in doc
        assert "search" in doc
        assert "get_product_investors" in doc

    @pytest.mark.asyncio
    @respx.mock
    async def test_catalog_walk_publishes_strategy_without_a_name(self) -> None:
        base_url = tenant("gp-cat")
        products = respx.get(f"{base_url}/products").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        _product(
                            _PRODUCT_ID,
                            name="Capstone Dispersion Fund",
                            short_name="CDSP",
                            values=_strategy_value(),
                        )
                    ],
                    "links": {"next": None},
                },
            )
        )
        _definitions_route(base_url)

        async with tool_client(base_url) as client:
            result = tool_model(
                await get_product(
                    ctx_never_elicit(),
                    custom_field_names=["Strategy"],
                    client=client,
                    custom_fields=custom_fields_service(client),
                    get_product_query=make_get_product_query(client),
                ),
                ProductResolvedResponse,
            )

        assert products.call_count == 1
        params = recorded_requests(products.calls)[0].url.params
        assert "fields" not in params
        assert result.scan_truncated is False
        payload = tool_payload(result)
        rows = [object_dict(item) for item in object_list(payload["products"])]
        assert rows[0]["id"] == _PRODUCT_ID
        assert rows[0]["short_name"] == "CDSP"
        fields = [object_dict(item) for item in object_list(rows[0]["custom_field_values"])]
        assert fields[0]["name"] == "Strategy"
        assert fields[0]["value"] == "Convertible Arbitrage"

    @pytest.mark.asyncio
    @respx.mock
    @pytest.mark.parametrize(
        ("case", "kwargs"),
        [("product", {"product": "Dispersion"}), ("search", {"search": "Dispersion"})],
    )
    async def test_named_product_fetches_the_full_record_after_resolve(
        self, case: str, kwargs: dict[str, str]
    ) -> None:
        base_url = tenant(f"gp-one-{case}")
        index = respx.get(f"{base_url}/products").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        _product(_PRODUCT_ID, name="Capstone Dispersion Fund", short_name="CDSP")
                    ],
                    "links": {"next": None},
                },
            )
        )
        detail = respx.get(f"{base_url}/products/{_PRODUCT_ID}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": _product(
                        _PRODUCT_ID,
                        name="Capstone Dispersion Fund",
                        short_name="CDSP",
                        values=_strategy_value(),
                    )
                },
            )
        )
        _definitions_route(base_url)

        async with tool_client(base_url) as client:
            result = tool_model(
                await get_product(
                    ctx_never_elicit(),
                    custom_field_names=["Strategy"],
                    client=client,
                    custom_fields=custom_fields_service(client),
                    get_product_query=make_get_product_query(client),
                    **kwargs,
                ),
                ProductResolvedResponse,
            )

        assert index.call_count >= 1
        assert "filter[name][like]" in recorded_requests(index.calls)[0].url.params
        assert detail.call_count == 1
        payload = tool_payload(result)
        rows = [object_dict(item) for item in object_list(payload["products"])]
        assert len(rows) == 1
        fields = [object_dict(item) for item in object_list(rows[0]["custom_field_values"])]
        assert fields[0]["value"] == "Convertible Arbitrage"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_trusted_id_is_one_request(self) -> None:
        """The full record already carries name and configuration, and 404s when absent."""
        base_url = tenant("gp-trusted-id")
        index = respx.get(f"{base_url}/products").mock(
            return_value=httpx.Response(200, json={"data": [], "links": {"next": None}})
        )
        detail = respx.get(f"{base_url}/products/{_PRODUCT_ID}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": _product(
                        _PRODUCT_ID,
                        name="Capstone Dispersion Fund",
                        short_name="CDSP",
                        values=_strategy_value(),
                    )
                },
            )
        )
        _definitions_route(base_url)

        async with tool_client(base_url) as client:
            result = tool_model(
                await get_product(
                    ctx_never_elicit(),
                    product_id=_PRODUCT_ID,
                    client=client,
                    custom_fields=custom_fields_service(client),
                    get_product_query=make_get_product_query(client),
                ),
                ProductResolvedResponse,
            )

        assert detail.call_count == 1
        assert index.call_count == 0
        assert [row.id for row in result.products] == [_PRODUCT_ID]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_missing_trusted_id_is_not_found(self) -> None:
        base_url = tenant("gp-missing-id")
        respx.get(f"{base_url}/products/{_PRODUCT_ID}").mock(
            return_value=httpx.Response(404, json={"errors": [{"title": "Not Found"}]})
        )
        _definitions_route(base_url)

        async with tool_client(base_url) as client:
            result = tool_model(
                await get_product(
                    ctx_never_elicit(),
                    product_id=_PRODUCT_ID,
                    client=client,
                    custom_fields=custom_fields_service(client),
                    get_product_query=make_get_product_query(client),
                ),
                NotFoundResponse,
            )

        assert result.query == _PRODUCT_ID
        assert result.scope == "products"

    @pytest.mark.asyncio
    @respx.mock
    async def test_product_and_search_together_fail_before_any_request(self) -> None:
        base_url = tenant("gp-both-names")
        products = respx.get(f"{base_url}/products")
        async with tool_client(base_url) as client:
            with pytest.raises(ValueError, match="Pass at most one of product or search"):
                await get_product(
                    ctx_never_elicit(),
                    product="Dispersion",
                    search="Keystone",
                    client=client,
                    custom_fields=custom_fields_service(client),
                    get_product_query=make_get_product_query(client),
                )
        assert products.call_count == 0
