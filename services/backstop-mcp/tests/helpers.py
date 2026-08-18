"""Shared test construction helpers.

Mirrors what `create_app()` does, minus the web layer: build one `BackstopClientFactory`, and
install it (plus a `CustomFieldsService`) in the single `runtime.Services` holder. Tests that
need a client go through the factory exactly as production does, so the concurrency gate and
config injection under test are the real ones.
"""

from collections.abc import Sequence
from datetime import date
from typing import Protocol, cast

import httpx
import respx
from pydantic import SecretStr

from backstop_mcp.app import retry_settings, transport_settings
from backstop_mcp.backstop_client.credential import BackstopCredentialSecret
from backstop_mcp.backstop_client.factory import BackstopClientFactory
from backstop_mcp.config import BackstopConfig
from backstop_mcp.features.activity_history import ActivityHistorySettings
from backstop_mcp.features.auth.context import BackstopAuthContext
from backstop_mcp.features.custom_fields import (
    CustomFieldsService,
    create_custom_fields_service,
)
from backstop_mcp.features.data_hygiene import (
    EmploymentIndexFactory,
    EmploymentRules,
    TypeVocabulary,
)
from backstop_mcp.features.opportunities import (
    OpportunityStagesService,
    create_opportunity_stages_service,
)
from backstop_mcp.server.runtime import Services, configure_services

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


def client_factory(
    base_url: str = BASE_URL,
    *,
    auth: BackstopAuthContext | None = None,
    **overrides: object,
) -> BackstopClientFactory:
    """Build a factory the way `create_app` does: config in, transport settings out.

    Goes through the same `app.transport_settings` / `app.retry_settings` translation as
    production rather than constructing settings directly, so a knob that stops being propagated
    at the composition root fails these tests too.
    """
    config = backstop_config(base_url, **overrides)
    return BackstopClientFactory(transport_settings(config), retry_settings(config), auth=auth)


def install_services(
    *,
    backstop: BackstopClientFactory,
    custom_fields: CustomFieldsService,
    employment_index_factory: EmploymentIndexFactory | None = None,
    activity_history_settings: ActivityHistorySettings | None = None,
    opportunity_stages: OpportunityStagesService | None = None,
) -> Services:
    services = Services(
        backstop=backstop,
        custom_fields=custom_fields,
        employment_index_factory=employment_index_factory or build_employment_index_factory(),
        activity_history=activity_history_settings
        or ActivityHistorySettings(page_size=10, gist_max_chars=300),
        opportunity_stages=opportunity_stages or opportunity_stages_service(),
    )
    configure_services(services)
    return services


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
        rules=EmploymentRules(
            employment=TypeVocabulary(
                type_ids=frozenset(employment_type_ids),
                name_markers=frozenset(
                    config.employment_relationship_type_markers
                    if employment_markers is None
                    else employment_markers
                ),
            ),
            former=TypeVocabulary(
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


def custom_fields_service(*, ttl_minutes: int = 60) -> CustomFieldsService:
    return create_custom_fields_service(ttl_minutes=ttl_minutes)


def opportunity_stages_service(*, ttl_minutes: int = 60) -> OpportunityStagesService:
    return create_opportunity_stages_service(ttl_minutes=ttl_minutes)


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


def resource(id: str, type: str, name: str | None = None, **attrs: object) -> dict[str, object]:
    attributes: dict[str, object] = {**attrs}
    if name is not None:
        attributes["name"] = name
    return {"type": type, "id": id, "attributes": attributes}


def collection(*resources: dict[str, object]) -> dict[str, object]:
    return {"data": list(resources)}
