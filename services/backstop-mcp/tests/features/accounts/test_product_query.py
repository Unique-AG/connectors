from collections.abc import Mapping, Sequence

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopApiError, BackstopClient
from tests.features.accounts.conftest import make_get_product_query
from tests.helpers import BASE_URL, recorded_requests

_PRODUCT_ID = "1653647"
_PRODUCTS_URL = f"{BASE_URL}/products"
_PRODUCT_URL = f"{BASE_URL}/products/{_PRODUCT_ID}"


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


class TestGetProductQuery:
    @pytest.mark.asyncio
    @respx.mock
    async def test_run_reads_the_full_record_without_a_fieldset(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCT_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": _product(
                        _PRODUCT_ID,
                        name="Capstone Dispersion Fund",
                        short_name="CDSP",
                        values=[{"definitionId": "501", "value": "Convertible Arbitrage"}],
                    )
                },
            )
        )

        fetched = await make_get_product_query(client).run(product_id=_PRODUCT_ID)

        assert fetched.product.id == _PRODUCT_ID
        assert fetched.product.short_name == "CDSP"
        assert fetched.stored_custom_field_values[0].value == "Convertible Arbitrage"
        assert "fields" not in recorded_requests(respx.calls)[0].url.params

    @pytest.mark.asyncio
    @respx.mock
    async def test_run_raises_when_the_product_is_missing(self, client: BackstopClient) -> None:
        respx.get(_PRODUCT_URL).mock(
            return_value=httpx.Response(404, json={"errors": [{"title": "Not Found"}]})
        )

        with pytest.raises(BackstopApiError) as exc_info:
            await make_get_product_query(client).run(product_id=_PRODUCT_ID)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    @respx.mock
    async def test_catalog_walks_without_a_fieldset(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(
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

        catalog = await make_get_product_query(client).catalog()

        assert [item.product.id for item in catalog.products] == [_PRODUCT_ID]
        assert catalog.scan_truncated is False
        assert "fields" not in recorded_requests(respx.calls)[0].url.params
