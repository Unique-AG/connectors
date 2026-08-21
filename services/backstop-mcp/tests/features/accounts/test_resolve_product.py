import logging

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopApiError, BackstopClient
from backstop_mcp.features.accounts import resolve_product
from backstop_mcp.features.resolution import Ambiguous, NotFound, Resolved
from tests.features.party_resolver.helpers import ctx_accept, ctx_decline, ctx_never_elicit
from tests.helpers import BASE_URL, collection, recorded_requests, resource

_PRODUCTS_URL = f"{BASE_URL}/products"
_PRODUCT_URL = f"{BASE_URL}/products/1292283"
_NEXT_PAGE = f"{BASE_URL}/products?page[offset]=200"


def _product(
    product_id: str,
    *,
    name: str | None = None,
    short_name: str | None = None,
) -> dict[str, object]:
    if short_name is None:
        return resource(product_id, "products", name=name)
    return resource(
        product_id,
        "products",
        name=name,
        configuration={"productShortName": short_name},
    )


def _document(product: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"data": product})


def _not_found(product_id: str) -> httpx.Response:
    return httpx.Response(
        404,
        json={
            "errors": [
                {
                    "code": "ResourceNotFoundException",
                    "title": f"Resource products not found by id {product_id}",
                }
            ]
        },
    )


def _index(*products: dict[str, object], next_url: str | None = None) -> httpx.Response:
    payload: dict[str, object] = collection(*products)
    if next_url is not None:
        payload["links"] = {"next": next_url}
    return httpx.Response(200, json=payload)


def _sample_index(*, next_url: str | None = None) -> httpx.Response:
    return _index(
        _product(
            "1292283",
            name="Capstone Global Unconstrained Portfolio",
            short_name="CGUP",
        ),
        _product("100", name="Blue Capital I", short_name="BLUC"),
        _product("101", name="Blue Capital II", short_name="BLUC"),
        next_url=next_url,
    )


class TestTheRequest:
    @pytest.mark.asyncio
    @respx.mock
    async def test_fetches_products_with_sparse_fieldset_and_page_limit_200(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(_PRODUCTS_URL).mock(return_value=_sample_index())

        result = await resolve_product(ctx_never_elicit(), client, product="CGUP")

        assert isinstance(result, Resolved)
        params = route.calls.last.request.url.params
        assert params["fields"] == "name,configuration"
        assert params["page[limit]"] == "200"
        assert params["filter[name][like]"] == "CGUP"
        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_does_not_call_quick_search(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_sample_index())
        quick = respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )

        await resolve_product(ctx_never_elicit(), client, product="CGUP")

        assert quick.call_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_walks_links_next_to_the_end_of_the_catalog(self, client: BackstopClient) -> None:
        route = respx.get(_PRODUCTS_URL).mock(
            side_effect=[
                _index(
                    _product("100", name="Blue Capital I", short_name="BLUC"), next_url=_NEXT_PAGE
                ),
                _index(_product("999", name="Page Two Fund", short_name="P2F")),
            ]
        )

        result = await resolve_product(ctx_never_elicit(), client, product="P2F")

        assert route.call_count == 2
        assert isinstance(result, Resolved)
        assert result.value.id == "999"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_trusted_id_does_not_read_the_catalog_at_all(
        self, client: BackstopClient
    ) -> None:
        """Catalog size cannot defeat an echoed id, because the catalog is never consulted."""
        catalog = respx.get(_PRODUCTS_URL).mock(return_value=_sample_index())
        route = respx.get(_PRODUCT_URL).mock(
            return_value=_document(
                _product(
                    "1292283",
                    name="Capstone Global Unconstrained Portfolio",
                    short_name="CGUP",
                )
            )
        )

        result = await resolve_product(ctx_never_elicit(), client, product_id="1292283")

        assert isinstance(result, Resolved)
        assert catalog.call_count == 0
        assert route.call_count == 1
        assert route.calls.last.request.url.params["fields"] == "name,configuration"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_small_catalog_does_not_warn(
        self, client: BackstopClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_sample_index())

        with caplog.at_level(logging.WARNING):
            await resolve_product(ctx_never_elicit(), client, product="CGUP")

        assert caplog.records == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_warns_when_the_catalog_is_large_enough_to_want_caching(
        self, client: BackstopClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        oversized = _index(
            # 401 exceeds the internal large-catalog warning threshold (400).
            *(
                _product(str(index), name=f"Fund {index}", short_name=f"F{index}")
                for index in range(401)
            )
        )
        respx.get(_PRODUCTS_URL).mock(return_value=oversized)

        with caplog.at_level(logging.WARNING):
            await resolve_product(ctx_never_elicit(), client, product="F1")

        assert [record.message for record in caplog.records] == ["accounts.products.index_large"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_name_like_miss_walks_the_unfiltered_catalog_for_a_short_name(
        self, client: BackstopClient
    ) -> None:
        def _respond(request: httpx.Request) -> httpx.Response:
            if request.url.params.get("filter[name][like]") == "CGUP":
                return _index()
            return _sample_index()

        route = respx.get(_PRODUCTS_URL).mock(side_effect=_respond)

        result = await resolve_product(ctx_never_elicit(), client, product="CGUP")

        assert isinstance(result, Resolved)
        assert result.value.short_name == "CGUP"
        assert route.call_count == 2
        calls = recorded_requests(route.calls)
        assert calls[0].url.params["filter[name][like]"] == "CGUP"
        assert "filter[name][like]" not in calls[1].url.params

    @pytest.mark.asyncio
    @respx.mock
    async def test_name_like_hit_does_not_walk_the_unfiltered_catalog(
        self, client: BackstopClient
    ) -> None:
        def _respond(request: httpx.Request) -> httpx.Response:
            if request.url.params.get("filter[name][like]") == "Dispersion":
                return _index(
                    _product("1653647", name="Capstone Dispersion Fund", short_name="CDSP")
                )
            raise AssertionError("unfiltered catalog must not be walked after a LIKE hit")

        route = respx.get(_PRODUCTS_URL).mock(side_effect=_respond)

        result = await resolve_product(ctx_never_elicit(), client, product="Dispersion")

        assert isinstance(result, Resolved)
        assert result.value.id == "1653647"
        assert route.call_count == 1


class TestResolveSearch:
    @pytest.mark.asyncio
    @respx.mock
    async def test_search_by_short_name_resolves(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_sample_index())

        result = await resolve_product(ctx_never_elicit(), client, product="CGUP")

        assert isinstance(result, Resolved)
        assert result.value.id == "1292283"
        assert result.value.name == "Capstone Global Unconstrained Portfolio"
        assert result.value.short_name == "CGUP"

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_by_id_resolves(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_sample_index())

        result = await resolve_product(ctx_never_elicit(), client, product="1292283")

        assert isinstance(result, Resolved)
        assert result.value.id == "1292283"

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_match_is_not_found(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_sample_index())

        result = await resolve_product(ctx_never_elicit(), client, product="Unknown Fund")

        assert isinstance(result, NotFound)
        assert result.query == "Unknown Fund"
        assert result.scope == "products"

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_by_name_substring_resolves(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_sample_index())
        quick = respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )

        result = await resolve_product(ctx_never_elicit(), client, product="Unconstrained")

        assert isinstance(result, Resolved)
        assert result.value.id == "1292283"
        assert result.value.short_name == "CGUP"
        assert quick.call_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_blank_product_is_not_found(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_sample_index())

        result = await resolve_product(ctx_never_elicit(), client, product="")

        assert isinstance(result, NotFound)
        assert result.query == ""
        assert result.scope == "products"

    @pytest.mark.asyncio
    @respx.mock
    async def test_whitespace_only_product_is_not_found(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_sample_index())

        result = await resolve_product(ctx_never_elicit(), client, product="   ")

        assert isinstance(result, NotFound)
        assert result.query == ""
        assert result.scope == "products"


class TestResolveProductId:
    @pytest.mark.asyncio
    @respx.mock
    async def test_product_id_is_fetched_by_id_and_hydrates_the_name(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCT_URL).mock(
            return_value=_document(
                _product(
                    "1292283",
                    name="Capstone Global Unconstrained Portfolio",
                    short_name="CGUP",
                )
            )
        )

        result = await resolve_product(ctx_never_elicit(), client, product_id="1292283")

        assert isinstance(result, Resolved)
        assert result.value.id == "1292283"
        assert result.value.name == "Capstone Global Unconstrained Portfolio"
        assert result.value.short_name == "CGUP"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_blank_product_id_is_not_found_without_a_request(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(url__startswith=_PRODUCTS_URL).mock(return_value=_sample_index())

        outcome = await resolve_product(ctx_never_elicit(), client, product_id="   ")

        assert isinstance(outcome, NotFound)
        assert route.call_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_404_is_not_found(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/products/999").mock(return_value=_not_found("999"))

        result = await resolve_product(ctx_never_elicit(), client, product_id="999")

        assert isinstance(result, NotFound)
        assert result.query == "999"
        assert result.scope == "products"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_non_404_error_stays_an_error(self, client: BackstopClient) -> None:
        """A 403 must not be reported to the model as "no such product"."""
        respx.get(_PRODUCT_URL).mock(
            return_value=httpx.Response(403, json={"errors": [{"title": "Forbidden"}]})
        )

        with pytest.raises(BackstopApiError) as exc_info:
            await resolve_product(ctx_never_elicit(), client, product_id="1292283")

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_null_data_document_is_also_not_found(self, client: BackstopClient) -> None:
        """Some by-id endpoints answer a missing record `200 {"data": null}` instead of 404."""
        respx.get(_PRODUCT_URL).mock(return_value=httpx.Response(200, json={"data": None}))

        result = await resolve_product(ctx_never_elicit(), client, product_id="1292283")

        assert isinstance(result, NotFound)
        assert result.query == "1292283"


class TestElicit:
    @pytest.mark.asyncio
    @respx.mock
    async def test_elicit_accept_resolves_selected_candidate(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_sample_index())

        result = await resolve_product(
            ctx_accept("Blue Capital II (BLUC)"),
            client,
            product="BLUC",
        )

        assert isinstance(result, Resolved)
        assert result.value.id == "101"
        assert result.value.name == "Blue Capital II"
        assert result.value.short_name == "BLUC"

    @pytest.mark.asyncio
    @respx.mock
    async def test_elicit_decline_returns_ambiguous(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_sample_index())

        result = await resolve_product(ctx_decline(), client, product="BLUC")

        assert isinstance(result, Ambiguous)
        assert [candidate.value.id for candidate in result.candidates] == ["100", "101"]
        assert result.query == "BLUC"
        assert result.scope == "products"


class TestInvalidArgs:
    @pytest.mark.asyncio
    async def test_rejects_both_product_id_and_product(self, client: BackstopClient) -> None:
        with pytest.raises(AssertionError, match="Exactly one of product_id or product"):
            await resolve_product(
                ctx_never_elicit(),
                client,
                product_id="1292283",
                product="CGUP",
            )

    @pytest.mark.asyncio
    async def test_rejects_neither_product_id_nor_product(self, client: BackstopClient) -> None:
        with pytest.raises(AssertionError, match="Exactly one of product_id or product"):
            await resolve_product(ctx_never_elicit(), client)


def _match_catalog() -> httpx.Response:
    """Wire page covering the match cases that a `/products` document can actually produce."""
    return _index(
        _product(
            "1292283",
            name="Capstone Global Unconstrained Portfolio",
            short_name="CGUP",
        ),
        _product("100", name="Blue Capital I", short_name="BLUC"),
        _product("101", name="Blue Capital II", short_name="BLUC"),
        _product("200", name="Alpha Growth Fund", short_name="AGRW"),
        _product("201", name="Alpha Value Fund", short_name="AVAL"),
        _product("600", name="No Short Name Fund"),
        _product("700", short_name="NONM"),
        _product("AbC", name="Other", short_name="OTHR"),
        _product("CGUP", name="Something Else", short_name="OTHER"),
        _product("801", name="Quiet Growth Vehicle"),
        _product("802", name="Quiet Value Vehicle"),
    )


class TestExactId:
    @pytest.mark.asyncio
    @respx.mock
    async def test_exact_id_resolves(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_match_catalog())

        result = await resolve_product(ctx_never_elicit(), client, product="1292283")

        assert isinstance(result, Resolved)
        assert result.value.id == "1292283"
        assert result.value.short_name == "CGUP"

    @pytest.mark.asyncio
    @respx.mock
    async def test_id_match_is_case_sensitive(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_match_catalog())

        result = await resolve_product(ctx_never_elicit(), client, product="abc")

        assert isinstance(result, NotFound)

    @pytest.mark.asyncio
    @respx.mock
    async def test_id_is_matched_before_short_name(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_match_catalog())

        result = await resolve_product(ctx_never_elicit(), client, product="CGUP")

        assert isinstance(result, Resolved)
        assert result.value.id == "CGUP"
        assert result.value.name == "Something Else"


class TestExactShortName:
    @pytest.mark.asyncio
    @respx.mock
    async def test_short_name_match_is_case_insensitive(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_sample_index())

        result = await resolve_product(ctx_never_elicit(), client, product="cgup")

        assert isinstance(result, Resolved)
        assert result.value.id == "1292283"

    @pytest.mark.asyncio
    @respx.mock
    async def test_nameless_product_resolves_by_short_name(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_match_catalog())

        result = await resolve_product(ctx_never_elicit(), client, product="NONM")

        assert isinstance(result, Resolved)
        assert result.value.id == "700"
        assert result.value.name is None
        assert result.value.short_name == "NONM"


class TestExactName:
    @pytest.mark.asyncio
    @respx.mock
    async def test_exact_name_resolves(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_match_catalog())

        result = await resolve_product(
            ctx_never_elicit(),
            client,
            product="Capstone Global Unconstrained Portfolio",
        )

        assert isinstance(result, Resolved)
        assert result.value.id == "1292283"

    @pytest.mark.asyncio
    @respx.mock
    async def test_name_match_is_case_insensitive(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_match_catalog())

        result = await resolve_product(
            ctx_never_elicit(),
            client,
            product="capstone global unconstrained portfolio",
        )

        assert isinstance(result, Resolved)
        assert result.value.id == "1292283"

    @pytest.mark.asyncio
    @respx.mock
    async def test_exact_name_is_matched_before_substring(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_match_catalog())

        result = await resolve_product(ctx_never_elicit(), client, product="Blue Capital I")

        assert isinstance(result, Resolved)
        assert result.value.id == "100"


class TestSubstringName:
    @pytest.mark.asyncio
    @respx.mock
    async def test_shared_substring_is_ambiguous(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_match_catalog())

        result = await resolve_product(ctx_decline(), client, product="Alpha")

        assert isinstance(result, Ambiguous)
        assert [candidate.value.id for candidate in result.candidates] == ["200", "201"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_substring_is_case_insensitive(self, client: BackstopClient) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_sample_index())

        result = await resolve_product(ctx_never_elicit(), client, product="unconstrained")

        assert isinstance(result, Resolved)
        assert result.value.id == "1292283"


class TestProductLabel:
    @pytest.mark.asyncio
    @respx.mock
    async def test_ambiguous_candidates_include_short_name_when_present(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_sample_index())

        result = await resolve_product(ctx_decline(), client, product="BLUC")

        assert isinstance(result, Ambiguous)
        assert [candidate.key for candidate in result.candidates] == ["100", "101"]
        assert [candidate.label for candidate in result.candidates] == [
            "Blue Capital I (BLUC)",
            "Blue Capital II (BLUC)",
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_ambiguous_candidates_use_name_alone_when_there_is_no_short_name(
        self, client: BackstopClient
    ) -> None:
        respx.get(_PRODUCTS_URL).mock(return_value=_match_catalog())

        result = await resolve_product(ctx_decline(), client, product="Quiet")

        assert isinstance(result, Ambiguous)
        assert [candidate.label for candidate in result.candidates] == [
            "Quiet Growth Vehicle",
            "Quiet Value Vehicle",
        ]
