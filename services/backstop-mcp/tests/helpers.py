"""Shared test construction helpers.

Helpers build a factory the way production does (`transport_settings` / `retry_settings`), not
a runtime holder. Tests that need a client go through the factory exactly as production does,
so the concurrency gate and config injection under test are the real ones.
"""

import json
from collections.abc import AsyncGenerator, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Protocol, cast

import httpx
import pytest
import respx
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import SecretStr

from backstop_mcp.backstop_client import (
    BackstopClient,
    BackstopClientFactory,
    BackstopCredentialSecret,
)
from backstop_mcp.config import BackstopConfig
from backstop_mcp.dependencies import retry_settings, transport_settings
from backstop_mcp.features.activity_tags import ActivityTagsService
from backstop_mcp.features.contact_categories import ListContactCategoriesQuery
from backstop_mcp.features.contact_sources import ListContactSourcesQuery
from backstop_mcp.features.custom_fields import CustomFieldGroupsService, CustomFieldsService
from backstop_mcp.features.data_hygiene import (
    EmploymentIndexFactory,
    EmploymentRulesDto,
    TypeVocabularyDto,
)
from backstop_mcp.features.opportunities import OpportunityStagesService
from backstop_mcp.features.system_users import SystemUsersService
from backstop_mcp.features.time_zones import TimeZonesService

BASE_URL = "https://example.backstopsolutions.com"

# Fixed "today" for departed-contact detection, so an end date in a fixture never becomes
# past-or-future depending on when the suite runs.
FIXED_TODAY = date(2026, 8, 5)


def credential(username: str = "bob.smith", token: str = "token") -> BackstopCredentialSecret:
    return BackstopCredentialSecret(username=username, api_token=SecretStr(token))


def backstop_config(base_url: str = BASE_URL, **overrides: object) -> BackstopConfig:
    """Build a config, applying `overrides` on top of the validated defaults.

    `model_copy` rather than passing the overrides to `__init__`: it keeps the helper's
    signature honest (`**overrides: object`, since a test may tune any field) without
    surrendering the constructor's own parameter types to `object`.
    """
    return BackstopConfig(base_url=base_url).model_copy(update=overrides)


@asynccontextmanager
async def tool_client(
    base_url: str = BASE_URL, **overrides: object
) -> AsyncGenerator[BackstopClient]:
    """A Backstop client for calling a tool with collaborators passed in as kwargs."""
    factory = client_factory(base_url, **overrides)
    try:
        yield factory.for_credential(credential())
    finally:
        await factory.aclose()


def client_factory(base_url: str = BASE_URL, **overrides: object) -> BackstopClientFactory:
    """Build a factory the way `create_app` does: config in, transport settings out.

    Goes through the same `dependencies.transport_settings` / `dependencies.retry_settings`
    translation as production rather than constructing settings directly, so a knob that stops
    being propagated at the composition root fails these tests too.
    """
    config = backstop_config(base_url, **overrides)
    return BackstopClientFactory(transport_settings(config), retry_settings(config))


def build_employment_index_factory(
    *,
    employment_type_ids: Sequence[str] = (),
    employment_markers: Sequence[str] | None = None,
    former_type_ids: Sequence[str] = (),
    former_markers: Sequence[str] | None = None,
    today: date = FIXED_TODAY,
) -> EmploymentIndexFactory:
    """A factory with the configured defaults and a fixed clock.

    Markers default to `BackstopConfig`'s rather than to empty, so a test that doesn't tune them
    exercises what a deployment actually runs.
    """
    config = backstop_config()
    return EmploymentIndexFactory(
        rules=EmploymentRulesDto(
            employment=TypeVocabularyDto(
                type_ids=frozenset(employment_type_ids),
                name_markers=frozenset(
                    config.employment_relationship_type_markers
                    if employment_markers is None
                    else employment_markers
                ),
            ),
            former=TypeVocabularyDto(
                type_ids=frozenset(former_type_ids),
                name_markers=frozenset(
                    config.former_employment_relationship_type_markers
                    if former_markers is None
                    else former_markers
                ),
            ),
        ),
        clock=lambda: today,
    )


def activity_tags_service(client: BackstopClient, *, ttl_minutes: int = 60) -> ActivityTagsService:
    return ActivityTagsService.with_ttl_minutes(client=client, ttl_minutes=ttl_minutes)


def list_contact_sources_query(
    client: BackstopClient, *, ttl_minutes: int = 60, caching_enabled: bool = True
) -> ListContactSourcesQuery:
    return ListContactSourcesQuery(
        client=client,
        ttl=timedelta(minutes=ttl_minutes),
        caching_enabled=caching_enabled,
    )


def list_contact_categories_query(
    client: BackstopClient, *, ttl_minutes: int = 60, caching_enabled: bool = True
) -> ListContactCategoriesQuery:
    return ListContactCategoriesQuery(
        client=client,
        ttl=timedelta(minutes=ttl_minutes),
        caching_enabled=caching_enabled,
    )


def system_users_service(client: BackstopClient, *, ttl_minutes: int = 60) -> SystemUsersService:
    return SystemUsersService.with_ttl_minutes(client=client, ttl_minutes=ttl_minutes)


def time_zones_service(client: BackstopClient, *, ttl_minutes: int = 60) -> TimeZonesService:
    return TimeZonesService.with_ttl_minutes(client=client, ttl_minutes=ttl_minutes)


def opportunity_stages_service(
    client: BackstopClient, *, ttl_minutes: int = 60
) -> OpportunityStagesService:
    return OpportunityStagesService.with_ttl_minutes(client=client, ttl_minutes=ttl_minutes)


def custom_fields_service(
    client: BackstopClient, *, ttl_minutes: int = 60, caching_enabled: bool = True
) -> CustomFieldsService:
    return CustomFieldsService.with_ttl_minutes(
        client=client, ttl_minutes=ttl_minutes, caching_enabled=caching_enabled
    )


def custom_field_groups_service(
    client: BackstopClient, *, ttl_minutes: int = 60
) -> CustomFieldGroupsService:
    return CustomFieldGroupsService.with_ttl_minutes(client=client, ttl_minutes=ttl_minutes)


class _RecordedCall(Protocol):
    @property
    def request(self) -> httpx.Request: ...


def recorded_requests(calls: object) -> list[httpx.Request]:
    """Every request a respx call log recorded, in call order.

    Takes either one route's `route.calls` or the module-level `respx.calls`. Neither is typed,
    so iterating them directly yields `Unknown`; and `route.calls.last` only ever shows the final
    request, which is no help when what is under test is the *set* of requests — as it is for
    offset paging, or for asserting a relationship was never followed.
    """
    return [call.request for call in cast("Sequence[_RecordedCall]", calls)]


def recorded_params(route: respx.Route) -> list[httpx.QueryParams]:
    """Query params of every call one respx route recorded, in call order."""
    return [request.url.params for request in recorded_requests(route.calls)]


def recorded_json_bodies(route: respx.Route) -> list[dict[str, object]]:
    """JSON bodies of every call one respx route recorded, in call order."""
    return [json.loads(request.content) for request in recorded_requests(route.calls)]


def resource(id: str, type: str, name: str | None = None, **attrs: object) -> dict[str, object]:
    attributes: dict[str, object] = {**attrs}
    if name is not None:
        attributes["name"] = name
    return {"type": type, "id": id, "attributes": attributes}


def collection(*resources: dict[str, object]) -> dict[str, object]:
    return {"data": list(resources)}


def contact_location(id: str, **attrs: object) -> dict[str, object]:
    """A `contact-locations` resource as `?include=contactLocations` side-loads it."""
    return {"type": "contact-locations", "id": id, "attributes": {**attrs}}


def assert_canary_absent(
    caplog: pytest.LogCaptureFixture, exporter: InMemorySpanExporter, canary: str
) -> None:
    """The canary is absent from every log record and every finished span.

    The MCP response itself may still contain it: that is the tool result the client asked for.
    """
    for record in caplog.records:
        assert not _contains_canary(record.getMessage(), canary), record.getMessage()
        assert not _contains_canary(record.__dict__, canary), record.__dict__
        if record.exc_info is not None:
            assert not _contains_canary(record.exc_info[1], canary), record.exc_info[1]
    for span in exporter.get_finished_spans():
        assert not _span_contains_canary(span, canary), span.name


def _span_contains_canary(span: ReadableSpan, canary: str) -> bool:
    if _contains_canary(span.name, canary):
        return True
    if _contains_canary(span.attributes, canary):
        return True
    if span.status.description is not None and canary in span.status.description:
        return True
    return any(
        _contains_canary(event.name, canary) or _contains_canary(event.attributes, canary)
        for event in span.events
    )


def _contains_canary(value: object, canary: str) -> bool:
    if isinstance(value, str):
        return canary in value
    if isinstance(value, bytes):
        return canary.encode() in value
    if isinstance(value, Mapping):
        pairs = cast("Mapping[object, object]", value)
        return any(
            _contains_canary(key, canary) or _contains_canary(item, canary)
            for key, item in pairs.items()
        )
    if isinstance(value, tuple | list | set | frozenset):
        return any(_contains_canary(item, canary) for item in cast("Iterable[object]", value))
    if value is None or isinstance(value, bool | int | float):
        return False
    return canary in str(value)


def linked_to_locations(
    party: dict[str, object], *locations: dict[str, object]
) -> dict[str, object]:
    """`party` with a `contactLocations` relationship pointing at `locations`."""
    return {
        **party,
        "relationships": {
            "contactLocations": {
                "data": [{"type": "contact-locations", "id": item["id"]} for item in locations]
            }
        },
    }
