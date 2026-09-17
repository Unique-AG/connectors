import logging
from typing import cast, get_args

import httpx
import pytest
import respx
from fastmcp.server.dependencies import without_injected_parameters
from pydantic import TypeAdapter
from pydantic.fields import FieldInfo

from backstop_mcp.features.contact_sources import ListContactSourcesResponse
from backstop_mcp.features.contact_sources.tools.list_contact_sources import list_contact_sources
from backstop_mcp.server.tools import TOOLS
from tests.helpers import (
    BASE_URL,
    list_contact_sources_query,
    recorded_requests,
    resource,
    tool_client,
)
from tests.server.tools.helpers import object_dict, tool_model, tool_payload

_INPUT: TypeAdapter[object] = TypeAdapter(without_injected_parameters(list_contact_sources))
_FETCH_LOGGER = "backstop_mcp.features.contact_sources.queries.list_contact_sources_query"

_LIVE_SOURCE_ID = "194859"


def tenant(name: str) -> str:
    """A distinct Backstop base URL per test so mocked routes cannot leak across cases."""
    return f"{BASE_URL}/{name}"


def _collection_page(*items: dict[str, object], next_url: str | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": list(items), "links": {"next": next_url}},
    )


def _source(
    source_id: str,
    *,
    name: str | None = None,
    **attrs: object,
) -> dict[str, object]:
    return resource(source_id, "contact-sources", name=name, **attrs)


def _referral() -> dict[str, object]:
    return _source(_LIVE_SOURCE_ID, name="Referral", description="Referral")


def _conference() -> dict[str, object]:
    return _source("196475", name="Conference", description="Conference")


def _unnamed_source() -> dict[str, object]:
    return _source("99", description="orphan")


class TestListContactSourcesTool:
    @pytest.mark.asyncio
    @respx.mock
    async def test_projects_id_name_and_description_from_one_collection_walk(self) -> None:
        base_url = tenant("cs-project")
        sources_route = respx.get(f"{base_url}/contact-sources").mock(
            return_value=_collection_page(_referral(), _unnamed_source(), _conference())
        )
        source_by_id = respx.get(f"{base_url}/contact-sources/{_LIVE_SOURCE_ID}").mock(
            return_value=httpx.Response(500)
        )

        async with tool_client(base_url) as client:
            result = tool_model(
                await list_contact_sources(
                    refresh=True,
                    list_contact_sources_query=list_contact_sources_query(client),
                ),
                ListContactSourcesResponse,
            )

        assert sources_route.call_count == 1
        requests = recorded_requests(sources_route.calls)
        assert requests[0].url.params["page[offset]"] == "0"
        assert requests[0].url.params["page[limit]"] == "100"
        assert "filter[name][like]" not in requests[0].url.params
        assert "filter[name][eq]" not in requests[0].url.params
        assert "include" not in requests[0].url.params
        assert source_by_id.call_count == 0
        assert not any(
            "/contact-sources/" in str(request.url.path)
            for request in recorded_requests(respx.calls)
            if request.url.path.rstrip("/") != "/contact-sources"
        )
        assert [source.id for source in result.sources] == [_LIVE_SOURCE_ID, "196475"]
        assert tool_payload(result) == {
            "status": "ok",
            "cache": "ok",
            "sources": [
                {
                    "id": _LIVE_SOURCE_ID,
                    "name": "Referral",
                    "description": "Referral",
                },
                {
                    "id": "196475",
                    "name": "Conference",
                    "description": "Conference",
                },
            ],
        }

    @pytest.mark.asyncio
    @respx.mock
    async def test_second_call_uses_cache_and_refresh_refetches(self) -> None:
        base_url = tenant("cs-cache")
        sources_route = respx.get(f"{base_url}/contact-sources").mock(
            return_value=_collection_page(_referral())
        )
        async with tool_client(base_url) as client:
            query = list_contact_sources_query(client)
            first = tool_model(
                await list_contact_sources(list_contact_sources_query=query),
                ListContactSourcesResponse,
            )
            second = tool_model(
                await list_contact_sources(list_contact_sources_query=query),
                ListContactSourcesResponse,
            )
            refreshed = tool_model(
                await list_contact_sources(refresh=True, list_contact_sources_query=query),
                ListContactSourcesResponse,
            )

        assert first.cache == "ok"
        assert second.cache == "ok"
        assert refreshed.cache == "ok"
        assert sources_route.call_count == 2
        assert [source.id for source in first.sources] == [_LIVE_SOURCE_ID]
        assert [source.id for source in second.sources] == [_LIVE_SOURCE_ID]
        assert [source.id for source in refreshed.sources] == [_LIVE_SOURCE_ID]

    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_failure_serves_stale(self) -> None:
        base_url = tenant("cs-stale")
        sources_route = respx.get(f"{base_url}/contact-sources").mock(
            return_value=_collection_page(_referral())
        )
        async with tool_client(base_url) as client:
            query = list_contact_sources_query(client)
            first = tool_model(
                await list_contact_sources(refresh=True, list_contact_sources_query=query),
                ListContactSourcesResponse,
            )
            sources_route.mock(side_effect=httpx.ConnectError("backstop down"))
            result = tool_model(
                await list_contact_sources(refresh=True, list_contact_sources_query=query),
                ListContactSourcesResponse,
            )

        assert first.cache == "ok"
        assert result.cache == "stale"
        assert result.sources[0].id == _LIVE_SOURCE_ID

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_filters_the_cached_catalog_without_a_like_request(self) -> None:
        base_url = tenant("cs-search")
        sources_route = respx.get(f"{base_url}/contact-sources").mock(
            return_value=_collection_page(_referral(), _conference())
        )
        async with tool_client(base_url) as client:
            query = list_contact_sources_query(client)
            first = tool_model(
                await list_contact_sources(
                    search="refer",
                    refresh=True,
                    list_contact_sources_query=query,
                ),
                ListContactSourcesResponse,
            )
            cached = tool_model(
                await list_contact_sources(
                    search="conference",
                    list_contact_sources_query=query,
                ),
                ListContactSourcesResponse,
            )

        assert sources_route.call_count == 1
        assert "filter[name][like]" not in recorded_requests(sources_route.calls)[0].url.params
        assert [source.id for source in first.sources] == [_LIVE_SOURCE_ID]
        assert [source.id for source in cached.sources] == ["196475"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_warns_and_retains_first_conflicting_source(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        base_url = tenant("cs-conflict")
        first_source = _referral()
        conflicting = _source(_LIVE_SOURCE_ID, name="Referral", description="changed")
        next_url = (
            f"{base_url}/contact-sources?page[offset]=100&page[limit]=100&sentinel=literal-next"
        )
        route = respx.get(f"{base_url}/contact-sources").mock(
            return_value=_collection_page(first_source)
        )
        async with tool_client(base_url) as client:
            query = list_contact_sources_query(client)
            first = tool_model(
                await list_contact_sources(refresh=True, list_contact_sources_query=query),
                ListContactSourcesResponse,
            )
            route.mock(
                side_effect=[
                    _collection_page(first_source, next_url=next_url),
                    _collection_page(conflicting),
                ]
            )
            with caplog.at_level(logging.WARNING, logger=_FETCH_LOGGER):
                refreshed = tool_model(
                    await list_contact_sources(refresh=True, list_contact_sources_query=query),
                    ListContactSourcesResponse,
                )

        assert first.sources[0].description == "Referral"
        assert route.call_count == 3
        assert refreshed.sources[0].description == "Referral"
        assert [
            record.getMessage() for record in caplog.records if record.name == _FETCH_LOGGER
        ] == [
            f"Conflicting contact sources for duplicate id {_LIVE_SOURCE_ID!r}; "
            + "retaining first source"
        ]


class TestListContactSourcesInput:
    def test_is_registered(self) -> None:
        assert list_contact_sources in TOOLS

    def test_accepts_search(self) -> None:
        properties = object_dict(object_dict(_INPUT.json_schema())["properties"])
        assert sorted(properties) == ["refresh", "search"]

    def test_refresh_is_only_for_a_user_reported_missing_source(self) -> None:
        doc = list_contact_sources.__doc__ or ""
        assert "refresh=true" in doc
        assert "missing source" in doc
        assert "contact-source" in doc.casefold() or "contact source" in doc.casefold()
        assert "custom field" in doc.casefold()
        assert "tenant" not in doc.casefold()
        for banned in (
            "northwind",
            "referral",
            "conference",
            "194859",
        ):
            assert banned not in doc.casefold()

        annotations = cast("dict[str, object]", list_contact_sources.__annotations__)
        field_info = next(
            item
            for item in cast("tuple[object, ...]", get_args(annotations["refresh"]))
            if isinstance(item, FieldInfo)
        )
        assert field_info.description is not None
        assert "missing source" in field_info.description
        assert "search" in without_injected_parameters(list_contact_sources).__annotations__
