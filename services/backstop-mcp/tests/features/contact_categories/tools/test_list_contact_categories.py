import logging
from typing import cast, get_args

import httpx
import pytest
import respx
from fastmcp.server.dependencies import without_injected_parameters
from pydantic import TypeAdapter
from pydantic.fields import FieldInfo

from backstop_mcp.features.contact_categories import ListContactCategoriesResponse
from backstop_mcp.features.contact_categories.tools.list_contact_categories import (
    list_contact_categories,
)
from backstop_mcp.server.tools import TOOLS
from tests.helpers import (
    BASE_URL,
    list_contact_categories_query,
    recorded_requests,
    resource,
    tool_client,
)
from tests.server.tools.helpers import object_dict, tool_model, tool_payload

_INPUT: TypeAdapter[object] = TypeAdapter(without_injected_parameters(list_contact_categories))
_FETCH_LOGGER = "backstop_mcp.features.contact_categories.queries.list_contact_categories_query"

_PROSPECT_ID = "1001"
_CLIENT_ID = "1002"


def tenant(name: str) -> str:
    """A distinct Backstop base URL per test so mocked routes cannot leak across cases."""
    return f"{BASE_URL}/{name}"


def _collection_page(*items: dict[str, object], next_url: str | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": list(items), "links": {"next": next_url}},
    )


def _category(category_id: str, *, name: str | None = None, **attrs: object) -> dict[str, object]:
    return resource(category_id, "contact-categories", name=name, **attrs)


def _prospect() -> dict[str, object]:
    return _category(_PROSPECT_ID, name="Prospect")


def _client() -> dict[str, object]:
    return _category(_CLIENT_ID, name="Client")


def _unnamed_category() -> dict[str, object]:
    return _category("99")


class TestListContactCategoriesTool:
    @pytest.mark.asyncio
    @respx.mock
    async def test_projects_id_and_name_from_one_collection_walk(self) -> None:
        base_url = tenant("cc-project")
        categories_route = respx.get(f"{base_url}/contact-categories").mock(
            return_value=_collection_page(_prospect(), _unnamed_category(), _client())
        )
        category_by_id = respx.get(f"{base_url}/contact-categories/{_PROSPECT_ID}").mock(
            return_value=httpx.Response(500)
        )

        async with tool_client(base_url) as client:
            result = tool_model(
                await list_contact_categories(
                    refresh=True,
                    list_contact_categories_query=list_contact_categories_query(client),
                ),
                ListContactCategoriesResponse,
            )

        assert categories_route.call_count == 1
        requests = recorded_requests(categories_route.calls)
        assert requests[0].url.params["page[offset]"] == "0"
        assert requests[0].url.params["page[limit]"] == "100"
        assert "filter[name][like]" not in requests[0].url.params
        assert "filter[name][eq]" not in requests[0].url.params
        assert "include" not in requests[0].url.params
        assert category_by_id.call_count == 0
        assert not any(
            "/contact-categories/" in str(request.url.path)
            for request in recorded_requests(respx.calls)
            if request.url.path.rstrip("/") != "/contact-categories"
        )
        assert [category.id for category in result.categories] == [_PROSPECT_ID, _CLIENT_ID]
        assert tool_payload(result) == {
            "status": "ok",
            "cache": "ok",
            "categories": [
                {"id": _PROSPECT_ID, "name": "Prospect"},
                {"id": _CLIENT_ID, "name": "Client"},
            ],
        }

    @pytest.mark.asyncio
    @respx.mock
    async def test_second_call_uses_cache_and_refresh_refetches(self) -> None:
        base_url = tenant("cc-cache")
        categories_route = respx.get(f"{base_url}/contact-categories").mock(
            return_value=_collection_page(_prospect())
        )
        async with tool_client(base_url) as client:
            query = list_contact_categories_query(client)
            first = tool_model(
                await list_contact_categories(list_contact_categories_query=query),
                ListContactCategoriesResponse,
            )
            second = tool_model(
                await list_contact_categories(list_contact_categories_query=query),
                ListContactCategoriesResponse,
            )
            refreshed = tool_model(
                await list_contact_categories(refresh=True, list_contact_categories_query=query),
                ListContactCategoriesResponse,
            )

        assert first.cache == "ok"
        assert second.cache == "ok"
        assert refreshed.cache == "ok"
        assert categories_route.call_count == 2
        assert [category.id for category in first.categories] == [_PROSPECT_ID]
        assert [category.id for category in second.categories] == [_PROSPECT_ID]
        assert [category.id for category in refreshed.categories] == [_PROSPECT_ID]

    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_failure_serves_stale(self) -> None:
        base_url = tenant("cc-stale")
        categories_route = respx.get(f"{base_url}/contact-categories").mock(
            return_value=_collection_page(_prospect())
        )
        async with tool_client(base_url) as client:
            query = list_contact_categories_query(client)
            first = tool_model(
                await list_contact_categories(refresh=True, list_contact_categories_query=query),
                ListContactCategoriesResponse,
            )
            categories_route.mock(side_effect=httpx.ConnectError("backstop down"))
            result = tool_model(
                await list_contact_categories(refresh=True, list_contact_categories_query=query),
                ListContactCategoriesResponse,
            )

        assert first.cache == "ok"
        assert result.cache == "stale"
        assert result.categories[0].id == _PROSPECT_ID

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_filters_the_cached_catalog_without_a_like_request(self) -> None:
        base_url = tenant("cc-search")
        categories_route = respx.get(f"{base_url}/contact-categories").mock(
            return_value=_collection_page(_prospect(), _client())
        )
        async with tool_client(base_url) as client:
            query = list_contact_categories_query(client)
            first = tool_model(
                await list_contact_categories(
                    search="prosp",
                    refresh=True,
                    list_contact_categories_query=query,
                ),
                ListContactCategoriesResponse,
            )
            cached = tool_model(
                await list_contact_categories(
                    search="client",
                    list_contact_categories_query=query,
                ),
                ListContactCategoriesResponse,
            )

        assert categories_route.call_count == 1
        assert "filter[name][like]" not in recorded_requests(categories_route.calls)[0].url.params
        assert [category.id for category in first.categories] == [_PROSPECT_ID]
        assert [category.id for category in cached.categories] == [_CLIENT_ID]

    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_warns_and_retains_first_conflicting_category(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        base_url = tenant("cc-conflict")
        first_category = _prospect()
        conflicting = _category(_PROSPECT_ID, name="Changed")
        next_url = (
            f"{base_url}/contact-categories?page[offset]=100&page[limit]=100&sentinel=literal-next"
        )
        route = respx.get(f"{base_url}/contact-categories").mock(
            return_value=_collection_page(first_category)
        )
        async with tool_client(base_url) as client:
            query = list_contact_categories_query(client)
            first = tool_model(
                await list_contact_categories(refresh=True, list_contact_categories_query=query),
                ListContactCategoriesResponse,
            )
            route.mock(
                side_effect=[
                    _collection_page(first_category, next_url=next_url),
                    _collection_page(conflicting),
                ]
            )
            with caplog.at_level(logging.WARNING, logger=_FETCH_LOGGER):
                refreshed = tool_model(
                    await list_contact_categories(
                        refresh=True, list_contact_categories_query=query
                    ),
                    ListContactCategoriesResponse,
                )

        assert first.categories[0].name == "Prospect"
        assert route.call_count == 3
        assert refreshed.categories[0].name == "Prospect"
        assert [
            record.getMessage() for record in caplog.records if record.name == _FETCH_LOGGER
        ] == [
            f"Conflicting contact categories for duplicate id {_PROSPECT_ID!r}; "
            + "retaining first category"
        ]


class TestListContactCategoriesInput:
    def test_is_registered(self) -> None:
        assert list_contact_categories in TOOLS

    def test_accepts_search(self) -> None:
        properties = object_dict(object_dict(_INPUT.json_schema())["properties"])
        assert sorted(properties) == ["refresh", "search"]

    def test_refresh_is_only_for_a_user_reported_missing_category(self) -> None:
        doc = list_contact_categories.__doc__ or ""
        assert "refresh=true" in doc
        assert "missing category" in doc
        assert "contact-category" in doc.casefold() or "contact category" in doc.casefold()
        assert "custom field" in doc.casefold()
        assert "tenant" not in doc.casefold()
        for banned in ("prospect", "client", "1001"):
            assert banned not in doc.casefold()

        annotations = cast("dict[str, object]", list_contact_categories.__annotations__)
        field_info = next(
            item
            for item in cast("tuple[object, ...]", get_args(annotations["refresh"]))
            if isinstance(item, FieldInfo)
        )
        assert field_info.description is not None
        assert "missing category" in field_info.description
        assert "search" in without_injected_parameters(list_contact_categories).__annotations__
