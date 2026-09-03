"""Wiring: each catalog service's `get()` hits Backstop once, then serves from cache.

The TTL / single-flight / serve-stale protocol lives on `CachedValue` and is exercised in
`tests/test_cached_value.py`. What is genuinely per-feature — which attributes survive the
projection, which rows are dropped — stays in that feature's own test file.

Each parameter case gets its own base URL prefix as well as its own per-test sub-path, so a
mocked route can leak neither across cases nor across tests.
"""

from collections.abc import AsyncGenerator, Callable, Generator, Mapping
from datetime import timedelta
from typing import ClassVar, Protocol

import httpx
import pytest
import respx
from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import BackstopClient, BackstopClientFactory
from backstop_mcp.caching import CacheFreshness
from backstop_mcp.dependencies import get_backstop_config
from backstop_mcp.features.activity_tags import ActivityTagsService, get_activity_tags_service
from backstop_mcp.features.custom_fields import (
    CustomFieldGroupsService,
    CustomFieldsService,
    get_custom_field_groups_service,
    get_custom_fields_service,
)
from backstop_mcp.features.system_users import SystemUsersService, get_system_users_service
from tests.helpers import BASE_URL, client_factory, credential, resource


def _unused_client() -> BackstopClient:
    return client_factory().for_credential(credential())


type ClientBuilder = Callable[[str], BackstopClient]
type _WiredCatalog = (
    ActivityTagsService | CustomFieldGroupsService | CustomFieldsService | SystemUsersService
)


class _NamedCatalogEntry(Protocol):
    """The one attribute every catalog DTO has, which is all this suite reads back."""

    @property
    def name(self) -> str | None: ...


class _CatalogService(Protocol):
    async def get(
        self, *, refresh: bool = False
    ) -> tuple[Mapping[str, _NamedCatalogEntry], CacheFreshness]: ...


class _CatalogUnderTest(BaseModel):
    """One catalog: how to build the service, and how to mock the walk it performs."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    slug: str
    path: str
    resource_type: str
    required_attributes: Mapping[str, object] = {}
    build: Callable[[BackstopClient, bool], _CatalogService]

    def service(self, client: BackstopClient, *, caching_enabled: bool = True) -> _CatalogService:
        return self.build(client, caching_enabled)

    def base_url(self, case: str) -> str:
        return f"{BASE_URL}/{self.slug}/{case}"

    def page(self, *rows: tuple[str, str]) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    resource(row_id, self.resource_type, name=name, **self.required_attributes)
                    for row_id, name in rows
                ],
                "links": {"next": None},
            },
        )

    def route(self, base_url: str, *rows: tuple[str, str]) -> respx.Route:
        return respx.get(f"{base_url}{self.path}").mock(return_value=self.page(*rows))


_CATALOGS: tuple[_CatalogUnderTest, ...] = (
    _CatalogUnderTest(
        slug="activity-tags",
        path="/activity-tags",
        resource_type="activity-tags",
        required_attributes={"quantityTagged": 3, "viewable": True},
        build=lambda client, caching: ActivityTagsService.with_ttl_minutes(
            client=client, ttl_minutes=60, caching_enabled=caching
        ),
    ),
    _CatalogUnderTest(
        slug="custom-field-groups",
        path="/custom-field-groups",
        resource_type="custom-field-groups",
        build=lambda client, caching: CustomFieldGroupsService.with_ttl_minutes(
            client=client, ttl_minutes=60, caching_enabled=caching
        ),
    ),
    _CatalogUnderTest(
        slug="system-users",
        path="/system-users",
        resource_type="system-users",
        build=lambda client, caching: SystemUsersService.with_ttl_minutes(
            client=client, ttl_minutes=60, caching_enabled=caching
        ),
    ),
    _CatalogUnderTest(
        slug="custom-field-definitions",
        path="/custom-field-definitions",
        resource_type="custom-field-definitions",
        required_attributes={"entityType": "OrganizationBean", "fieldType": "text"},
        build=lambda client, caching: CustomFieldsService.with_ttl_minutes(
            client=client, ttl_minutes=60, caching_enabled=caching
        ),
    ),
)


@pytest.fixture
async def clients() -> AsyncGenerator[ClientBuilder]:
    """Build a client per Backstop base URL.

    Each test uses its own sub-path as a distinct "instance" so mocked routes cannot leak
    across cases. The factory owns the base URL, so one is created per URL and all of them
    are closed together.
    """
    built: list[BackstopClientFactory] = []

    def make(base_url: str) -> BackstopClient:
        factory = client_factory(base_url)
        built.append(factory)
        return factory.for_credential(credential("schema-bob"))

    yield make
    for factory in built:
        await factory.aclose()


@pytest.mark.parametrize("catalog", _CATALOGS, ids=[case.slug for case in _CATALOGS])
class TestCatalogServiceWiresThroughCachedValue:
    @pytest.mark.asyncio
    @respx.mock
    async def test_first_fetch_caches_by_id_and_second_get_does_not_rehit(
        self, catalog: _CatalogUnderTest, clients: ClientBuilder
    ) -> None:
        base_url = catalog.base_url("ttl-fresh")
        client = clients(base_url)
        service = catalog.service(client)
        route = catalog.route(base_url, ("7", "Cached Entry"))

        first, first_cache = await service.get()
        second, second_cache = await service.get()

        assert route.call_count == 1
        assert first_cache == "ok"
        assert second_cache == "ok"
        assert list(first) == ["7"]
        assert first["7"].name == "Cached Entry"
        assert second["7"].name == "Cached Entry"

    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_fetches_even_when_fresh(
        self, catalog: _CatalogUnderTest, clients: ClientBuilder
    ) -> None:
        base_url = catalog.base_url("ttl-refresh")
        client = clients(base_url)
        service = catalog.service(client)
        route = respx.get(f"{base_url}{catalog.path}").mock(
            side_effect=[
                catalog.page(("old-1", "Cached Entry")),
                catalog.page(("new-1", "Refreshed Entry")),
            ]
        )

        await service.get()
        entries, cache = await service.get(refresh=True)

        assert route.call_count == 2
        assert cache == "ok"
        assert [entry.name for entry in entries.values()] == ["Refreshed Entry"]


class TestCachingFlagsComeFromTheEnvironment:
    """Turning one catalog's cache on is an env var, not a deploy of new code.

    The flag is per feature and mirrors the TTL knob it governs, so the two custom-field catalogs
    share one — they already share `custom_field_schema_ttl_minutes`. Asserted through the real
    providers because the wiring is the whole feature: a flag that never reaches `CachedValue`
    reads exactly like a working one.
    """

    _PROVIDERS: ClassVar[tuple[Callable[[BackstopClient], _WiredCatalog], ...]] = (
        get_activity_tags_service,
        get_system_users_service,
        get_custom_fields_service,
        get_custom_field_groups_service,
    )
    _FLAGS: ClassVar[tuple[str, ...]] = (
        "BACKSTOP_ACTIVITY_TAG_CACHE_ENABLED",
        "BACKSTOP_SYSTEM_USER_CACHE_ENABLED",
        "BACKSTOP_CUSTOM_FIELD_SCHEMA_CACHE_ENABLED",
    )

    @pytest.fixture(autouse=True)
    def _fresh_providers(self) -> Generator[None]:
        """Providers are `lru_cache(maxsize=1)`, so each case needs them rebuilt — and so does
        whatever runs next, since a service built here would otherwise outlive this test.

        `get_backstop_config` is cleared with them: it caches the very env vars under test.
        """
        self._clear_caches()
        yield
        self._clear_caches()

    @staticmethod
    def _clear_caches() -> None:
        get_backstop_config.cache_clear()
        for provider in (
            get_activity_tags_service,
            get_system_users_service,
            get_custom_fields_service,
            get_custom_field_groups_service,
        ):
            provider.cache_clear()

    @staticmethod
    def _enabled(service: _WiredCatalog) -> bool:
        return service._cache._caching_enabled  # pyright: ignore[reportPrivateUsage]

    def test_catalogs_ship_with_custom_field_cache_on_and_the_rest_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for flag in self._FLAGS:
            monkeypatch.delenv(flag, raising=False)

        unused = _unused_client()
        tags, users, fields, groups = (provider(unused) for provider in self._PROVIDERS)
        assert self._enabled(tags) is False
        assert self._enabled(users) is False
        assert self._enabled(fields) is True
        assert self._enabled(groups) is True

    def test_a_flag_enables_only_its_own_feature(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The point of per-feature flags: one catalog's numbers cannot commit the others."""
        for flag in self._FLAGS:
            monkeypatch.delenv(flag, raising=False)
        monkeypatch.setenv("BACKSTOP_ACTIVITY_TAG_CACHE_ENABLED", "true")
        monkeypatch.setenv("BACKSTOP_CUSTOM_FIELD_SCHEMA_CACHE_ENABLED", "false")

        unused = _unused_client()
        tags, users, fields, groups = (provider(unused) for provider in self._PROVIDERS)

        assert self._enabled(tags) is True
        assert self._enabled(users) is False
        assert self._enabled(fields) is False
        assert self._enabled(groups) is False

    def test_the_custom_field_flag_covers_both_of_that_features_catalogs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for flag in self._FLAGS:
            monkeypatch.delenv(flag, raising=False)
        monkeypatch.setenv("BACKSTOP_CUSTOM_FIELD_SCHEMA_CACHE_ENABLED", "false")

        unused = _unused_client()
        assert self._enabled(get_custom_fields_service(unused)) is False
        assert self._enabled(get_custom_field_groups_service(unused)) is False

        self._clear_caches()
        monkeypatch.setenv("BACKSTOP_CUSTOM_FIELD_SCHEMA_CACHE_ENABLED", "true")

        unused = _unused_client()
        assert self._enabled(get_custom_fields_service(unused)) is True
        assert self._enabled(get_custom_field_groups_service(unused)) is True

    def test_an_enabled_catalog_still_takes_its_ttl_from_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The flag decides whether the TTL is consulted, not what it is."""
        monkeypatch.setenv("BACKSTOP_ACTIVITY_TAG_CACHE_ENABLED", "true")
        monkeypatch.setenv("BACKSTOP_ACTIVITY_TAG_TTL_MINUTES", "90")

        service = get_activity_tags_service(_unused_client())

        assert service._cache._freshness.duration == timedelta(minutes=90)  # pyright: ignore[reportPrivateUsage]
