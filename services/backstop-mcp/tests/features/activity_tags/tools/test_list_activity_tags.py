import logging
from typing import cast, get_args

import httpx
import pytest
import respx
from fastmcp.server.dependencies import without_injected_parameters
from pydantic import TypeAdapter
from pydantic.fields import FieldInfo

from backstop_mcp.features.activity_tags.tools.list_activity_tags import (
    ListActivityTagsResponse,
    list_activity_tags,
)
from tests.helpers import (
    BASE_URL,
    activity_tags_service,
    recorded_requests,
    resource,
    tool_client,
)
from tests.server.tools.helpers import object_dict, tool_model, tool_payload

_INPUT: TypeAdapter[object] = TypeAdapter(without_injected_parameters(list_activity_tags))
_FETCH_LOGGER = "backstop_mcp.features.activity_tags.fetch_activity_tags"

_LIVE_TAG_ID = "474963"


def tenant(name: str) -> str:
    """A distinct Backstop base URL per test so mocked routes cannot leak across cases."""
    return f"{BASE_URL}/{name}"


def _collection_page(*items: dict[str, object], next_url: str | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": list(items), "links": {"next": next_url}},
    )


def _tag(
    tag_id: str,
    *,
    name: str | None = None,
    relationships: dict[str, object] | None = None,
    **attrs: object,
) -> dict[str, object]:
    row = resource(tag_id, "activity-tags", name=name, **attrs)
    if relationships is not None:
        row["relationships"] = relationships
    return row


def _quarterly_review(*, base_url: str) -> dict[str, object]:
    return _tag(
        _LIVE_TAG_ID,
        name="Quarterly Review",
        quantityTagged=12,
        viewable=True,
        relationships={
            "activities": {
                "links": {
                    "self": f"{base_url}/activity-tags/{_LIVE_TAG_ID}/relationships/activities",
                    "related": f"{base_url}/activity-tags/{_LIVE_TAG_ID}/activities",
                }
            }
        },
    )


def _hidden_unused() -> dict[str, object]:
    return _tag("88", name="Internal Scratch", quantityTagged=0, viewable=False)


def _unnamed_tag() -> dict[str, object]:
    return _tag("99", quantityTagged=3, viewable=True)


class TestListActivityTagsTool:
    @pytest.mark.asyncio
    @respx.mock
    async def test_projects_id_name_quantity_and_viewable_from_one_collection_walk(self) -> None:
        base_url = tenant("at-project")
        tags_route = respx.get(f"{base_url}/activity-tags").mock(
            return_value=_collection_page(
                _quarterly_review(base_url=base_url),
                _unnamed_tag(),
                _hidden_unused(),
            )
        )
        tag_by_id = respx.get(f"{base_url}/activity-tags/{_LIVE_TAG_ID}").mock(
            return_value=httpx.Response(500)
        )
        activities_related = respx.get(f"{base_url}/activity-tags/{_LIVE_TAG_ID}/activities").mock(
            return_value=httpx.Response(500)
        )
        activities_rel = respx.get(
            f"{base_url}/activity-tags/{_LIVE_TAG_ID}/relationships/activities"
        ).mock(return_value=httpx.Response(500))

        async with tool_client(base_url) as client:
            result = tool_model(
                await list_activity_tags(
                    refresh=True,
                    client=client,
                    activity_tags=activity_tags_service(),
                ),
                ListActivityTagsResponse,
            )

        assert tags_route.call_count == 1
        requests = recorded_requests(tags_route.calls)
        assert requests[0].url.params["page[offset]"] == "0"
        assert requests[0].url.params["page[limit]"] == "1000"
        assert "filter[name][like]" not in requests[0].url.params
        assert "include" not in requests[0].url.params
        assert tag_by_id.call_count == 0
        assert activities_related.call_count == 0
        assert activities_rel.call_count == 0
        assert not any(
            "/activity-tags/" in str(request.url.path)
            for request in recorded_requests(respx.calls)
            if request.url.path.rstrip("/") != "/activity-tags"
        )
        assert [tag.id for tag in result.tags] == [_LIVE_TAG_ID, "88"]
        assert tool_payload(result) == {
            "status": "ok",
            "cache": "ok",
            "tags": [
                {
                    "id": _LIVE_TAG_ID,
                    "name": "Quarterly Review",
                    "quantity_tagged": 12,
                    "viewable": True,
                },
                {
                    "id": "88",
                    "name": "Internal Scratch",
                    "quantity_tagged": 0,
                    "viewable": False,
                },
            ],
        }

    @pytest.mark.asyncio
    @respx.mock
    async def test_second_call_uses_cache_and_refresh_refetches(self) -> None:
        base_url = tenant("at-cache")
        tags_route = respx.get(f"{base_url}/activity-tags").mock(
            return_value=_collection_page(_quarterly_review(base_url=base_url))
        )
        tags = activity_tags_service()

        async with tool_client(base_url) as client:
            first = tool_model(
                await list_activity_tags(client=client, activity_tags=tags),
                ListActivityTagsResponse,
            )
            second = tool_model(
                await list_activity_tags(client=client, activity_tags=tags),
                ListActivityTagsResponse,
            )
            refreshed = tool_model(
                await list_activity_tags(refresh=True, client=client, activity_tags=tags),
                ListActivityTagsResponse,
            )

        assert first.cache == "ok"
        assert second.cache == "ok"
        assert refreshed.cache == "ok"
        assert tags_route.call_count == 2
        assert [tag.id for tag in first.tags] == [_LIVE_TAG_ID]
        assert [tag.id for tag in second.tags] == [_LIVE_TAG_ID]
        assert [tag.id for tag in refreshed.tags] == [_LIVE_TAG_ID]

    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_failure_serves_stale(self) -> None:
        base_url = tenant("at-stale")
        tags_route = respx.get(f"{base_url}/activity-tags").mock(
            return_value=_collection_page(_quarterly_review(base_url=base_url))
        )
        tags = activity_tags_service()

        async with tool_client(base_url) as client:
            first = tool_model(
                await list_activity_tags(refresh=True, client=client, activity_tags=tags),
                ListActivityTagsResponse,
            )
            tags_route.mock(side_effect=httpx.ConnectError("backstop down"))
            result = tool_model(
                await list_activity_tags(refresh=True, client=client, activity_tags=tags),
                ListActivityTagsResponse,
            )

        assert first.cache == "ok"
        assert result.cache == "stale"
        assert result.tags[0].id == _LIVE_TAG_ID

    @pytest.mark.asyncio
    @respx.mock
    async def test_collapses_equivalent_duplicates_across_pages_without_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        base_url = tenant("at-list-deduplicated")
        tag = _quarterly_review(base_url=base_url)
        next_url = (
            f"{base_url}/activity-tags?page[offset]=1000&page[limit]=1000&sentinel=literal-next"
        )
        route = respx.get(f"{base_url}/activity-tags").mock(
            side_effect=[
                _collection_page(tag, next_url=next_url),
                _collection_page(_quarterly_review(base_url=base_url)),
            ]
        )

        async with tool_client(base_url) as client:
            with caplog.at_level(logging.WARNING, logger=_FETCH_LOGGER):
                result = tool_model(
                    await list_activity_tags(
                        refresh=True,
                        client=client,
                        activity_tags=activity_tags_service(),
                    ),
                    ListActivityTagsResponse,
                )

        assert route.call_count == 2
        requests = recorded_requests(route.calls)
        assert requests[0].url.params["page[offset]"] == "0"
        assert requests[0].url.params["page[limit]"] == "1000"
        assert str(requests[1].url) == next_url
        assert not any(
            record.name == _FETCH_LOGGER and record.levelno >= logging.WARNING
            for record in caplog.records
        )
        assert tool_payload(result) == {
            "status": "ok",
            "cache": "ok",
            "tags": [
                {
                    "id": _LIVE_TAG_ID,
                    "name": "Quarterly Review",
                    "quantity_tagged": 12,
                    "viewable": True,
                }
            ],
        }

    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_warns_and_retains_first_conflicting_tag(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        base_url = tenant("at-list-conflicting-duplicates")
        first_tag = _quarterly_review(base_url=base_url)
        conflicting_tag = _tag(
            _LIVE_TAG_ID,
            name="Quarterly Review",
            quantityTagged=99,
            viewable=True,
        )
        next_url = (
            f"{base_url}/activity-tags?page[offset]=1000&page[limit]=1000&sentinel=literal-next"
        )
        route = respx.get(f"{base_url}/activity-tags").mock(
            return_value=_collection_page(first_tag)
        )
        tags = activity_tags_service()

        async with tool_client(base_url) as client:
            first = tool_model(
                await list_activity_tags(
                    refresh=True,
                    client=client,
                    activity_tags=tags,
                ),
                ListActivityTagsResponse,
            )
            route.mock(
                side_effect=[
                    _collection_page(first_tag, next_url=next_url),
                    _collection_page(conflicting_tag),
                ]
            )
            with caplog.at_level(logging.WARNING, logger=_FETCH_LOGGER):
                refreshed = tool_model(
                    await list_activity_tags(
                        refresh=True,
                        client=client,
                        activity_tags=tags,
                    ),
                    ListActivityTagsResponse,
                )

        assert first.cache == "ok"
        assert first.tags[0].quantity_tagged == 12
        assert route.call_count == 3
        requests = recorded_requests(route.calls)
        assert requests[1].url.params["page[offset]"] == "0"
        assert requests[1].url.params["page[limit]"] == "1000"
        assert str(requests[2].url) == next_url
        assert refreshed.status == "ok"
        assert refreshed.cache == "ok"
        assert len(refreshed.tags) == 1
        assert refreshed.tags[0].quantity_tagged == 12
        assert [
            record.getMessage() for record in caplog.records if record.name == _FETCH_LOGGER
        ] == [f"Conflicting activity tags for duplicate id {_LIVE_TAG_ID!r}; retaining first tag"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_filters_the_cached_catalog_without_a_like_request(self) -> None:
        base_url = tenant("at-search")
        tags_route = respx.get(f"{base_url}/activity-tags").mock(
            return_value=_collection_page(
                _quarterly_review(base_url=base_url),
                _hidden_unused(),
            )
        )
        tags = activity_tags_service()

        async with tool_client(base_url) as client:
            first = tool_model(
                await list_activity_tags(
                    search="quarterly",
                    refresh=True,
                    client=client,
                    activity_tags=tags,
                ),
                ListActivityTagsResponse,
            )
            cached = tool_model(
                await list_activity_tags(
                    search="scratch",
                    client=client,
                    activity_tags=tags,
                ),
                ListActivityTagsResponse,
            )

        assert tags_route.call_count == 1
        assert "filter[name][like]" not in recorded_requests(tags_route.calls)[0].url.params
        assert [tag.id for tag in first.tags] == [_LIVE_TAG_ID]
        assert [tag.id for tag in cached.tags] == ["88"]


class TestListActivityTagsInput:
    def test_accepts_search(self) -> None:
        # Asserted over the adapter's schema, not by validating a payload: `_INPUT` wraps the
        # tool callable, so `validate_python` would validate the arguments and then *call* it,
        # leaving an un-awaited coroutine behind.
        properties = object_dict(object_dict(_INPUT.json_schema())["properties"])
        assert sorted(properties) == ["refresh", "search"]

    def test_refresh_is_only_for_a_user_reported_missing_field(self) -> None:
        doc = list_activity_tags.__doc__ or ""
        assert "refresh=true" in doc
        assert "missing field" in doc
        assert "activity-tag" in doc.casefold() or "activity tag" in doc.casefold()
        assert "tenant" not in doc.casefold()
        for banned in (
            "capstone",
            "at: meeting",
            "at: dispersion",
            "cvm ddq",
            "301",
        ):
            assert banned not in doc.casefold()

        annotations = cast("dict[str, object]", list_activity_tags.__annotations__)
        field_info = next(
            item
            for item in cast("tuple[object, ...]", get_args(annotations["refresh"]))
            if isinstance(item, FieldInfo)
        )
        assert field_info.description is not None
        assert "missing field" in field_info.description
        assert "search" in without_injected_parameters(list_activity_tags).__annotations__
