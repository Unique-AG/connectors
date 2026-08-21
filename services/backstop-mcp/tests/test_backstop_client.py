import asyncio
import base64
import time
from collections.abc import AsyncGenerator
from typing import cast

import httpx
import pytest
import respx
from pydantic import BaseModel, ValidationError

from backstop_mcp.backstop_client import (
    BackstopApiError,
    BackstopAuthError,
    BackstopClientFactory,
    BackstopCredentialSecret,
    BackstopRateLimitError,
    BackstopResponseSchemaError,
    BackstopUnreachableError,
    BackstopUntrustedUrlError,
    PageResult,
    SinglePage,
)
from backstop_mcp.config import BackstopConfig
from tests.helpers import BASE_URL as _BASE_URL
from tests.helpers import client_factory, credential, recorded_params

_BASIC_AUTH = "Basic " + base64.b64encode(b"bob.smith:p@55W0rd321!").decode()


class _Record(BaseModel):
    id: str


class _Widget(BaseModel):
    id: str
    label: str


def _credential(
    username: str = "bob.smith", api_token: str = "p@55W0rd321!"
) -> BackstopCredentialSecret:
    return credential(username, api_token)


@pytest.fixture
async def factory() -> AsyncGenerator[BackstopClientFactory]:
    built = client_factory()
    yield built
    await built.aclose()


def _read_timeout(route: respx.Route) -> float:
    """The read timeout httpx recorded on the outbound request.

    httpx stores the resolved timeout in `request.extensions`, which is a public part of the
    request — no need to monkeypatch the shared client to observe it.
    """
    extensions = cast("dict[str, dict[str, float]]", route.calls.last.request.extensions)
    return extensions["timeout"]["read"]


class TestForCredential:
    @pytest.mark.asyncio
    @respx.mock
    async def test_builds_client_scoped_to_the_credential(
        self, factory: BackstopClientFactory
    ) -> None:
        route = respx.get(f"{_BASE_URL}/system-info").mock(
            return_value=httpx.Response(200, json={})
        )

        await factory.for_credential(_credential()).raw_request("GET", "/system-info")

        sent_request = route.calls.last.request
        assert sent_request.headers["authorization"] == _BASIC_AUTH
        assert sent_request.headers["token"] == "true"

    def test_uses_the_injected_config_not_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A deployment's tuning must survive into every request.

        The client used to construct its own `BackstopConfig()` per call, so anything
        `create_app` was handed was silently discarded. The factory owns the one config.
        """
        monkeypatch.setenv("BACKSTOP_DEFAULT_PAGE_SIZE", "7")
        built = client_factory(default_page_size=250)

        assert built.settings.default_page_size == 250


class TestBackstopClientAutoRaises:
    """Every error response maps to a typed exception — tools never check status codes."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_backstop_auth_error_on_401(self, factory: BackstopClientFactory) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(401))

        with pytest.raises(BackstopAuthError):
            await factory.for_credential(_credential()).raw_request("GET", "/system-info")

    @pytest.mark.asyncio
    @respx.mock
    async def test_calls_auth_failure_hook_on_401(self, factory: BackstopClientFactory) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(401))
        revoked: list[bool] = []

        async def on_auth_failure() -> None:
            revoked.append(True)

        client = factory.for_credential(_credential(), on_auth_failure=on_auth_failure)
        with pytest.raises(BackstopAuthError):
            await client.raw_request("GET", "/system-info")

        assert revoked == [True]

    @pytest.mark.asyncio
    @respx.mock
    async def test_auth_failure_hook_error_still_raises_backstop_auth_error(
        self, factory: BackstopClientFactory
    ) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(401))

        async def on_auth_failure() -> None:
            raise RuntimeError("revoke failed")

        client = factory.for_credential(_credential(), on_auth_failure=on_auth_failure)
        with pytest.raises(BackstopAuthError):
            await client.raw_request("GET", "/system-info")

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_backstop_api_error_on_other_error_statuses(
        self, factory: BackstopClientFactory
    ) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(
            return_value=httpx.Response(500, json={"errors": [{"detail": "Something broke"}]})
        )

        with pytest.raises(BackstopApiError) as exc_info:
            await factory.for_credential(_credential()).raw_request("GET", "/system-info")

        assert exc_info.value.detail == "Something broke"

    @pytest.mark.asyncio
    @respx.mock
    async def test_does_not_raise_on_200(self, factory: BackstopClientFactory) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(
            return_value=httpx.Response(200, json={"version": "1.0"})
        )

        result = await factory.for_credential(_credential()).raw_request("GET", "/system-info")

        assert result.json() == {"version": "1.0"}


class TestHeaders:
    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_shared_defaults_and_per_call_authorization(
        self, factory: BackstopClientFactory
    ) -> None:
        route = respx.get(f"{_BASE_URL}/system-info").mock(
            return_value=httpx.Response(200, json={})
        )

        await factory.for_credential(_credential()).raw_request("GET", "/system-info")

        sent_request = route.calls.last.request
        assert sent_request.headers["token"] == "true"
        assert sent_request.headers["accept"] == "application/vnd.api+json"
        assert sent_request.headers["content-type"] == "application/vnd.api+json"
        assert sent_request.headers["authorization"] == _BASIC_AUTH


class TestTimeoutProfiles:
    @pytest.mark.asyncio
    @respx.mock
    async def test_reports_path_uses_extended_timeout(self, factory: BackstopClientFactory) -> None:
        route = respx.get(f"{_BASE_URL}/reports").mock(return_value=httpx.Response(200, json={}))

        await factory.for_credential(_credential()).raw_request("GET", "/reports")

        assert _read_timeout(route) == BackstopConfig().reports_timeout_seconds

    @pytest.mark.asyncio
    @respx.mock
    async def test_crud_path_uses_default_timeout(self, factory: BackstopClientFactory) -> None:
        route = respx.get(f"{_BASE_URL}/deals/1").mock(return_value=httpx.Response(200, json={}))

        await factory.for_credential(_credential()).raw_request("GET", "/deals/1")

        assert _read_timeout(route) == BackstopConfig().default_timeout_seconds


class _InFlightTracker:
    """Counts concurrent handler invocations, releasing them all on demand."""

    release: asyncio.Event
    in_flight: int
    max_in_flight: int

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.in_flight = 0
        self.max_in_flight = 0

    async def handle(self, _request: httpx.Request) -> httpx.Response:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await self.release.wait()
        self.in_flight -= 1
        return httpx.Response(200, json={})


class TestConcurrencyGate:
    @pytest.mark.asyncio
    @respx.mock
    async def test_at_most_five_requests_in_flight_across_separate_clients(
        self, factory: BackstopClientFactory
    ) -> None:
        tracker = _InFlightTracker()
        respx.get(f"{_BASE_URL}/system-info").mock(side_effect=tracker.handle)
        cred = _credential(username="concurrency.user")

        async def call() -> httpx.Response:
            return await factory.for_credential(cred).raw_request("GET", "/system-info")

        tasks = [asyncio.create_task(call()) for _ in range(6)]
        await asyncio.sleep(0.05)

        assert tracker.max_in_flight == 5
        assert tracker.in_flight == 5

        tracker.release.set()
        await asyncio.gather(*tasks)
        assert tracker.max_in_flight == 5

    @pytest.mark.asyncio
    @respx.mock
    async def test_gate_bounds_a_fan_out_from_one_client(
        self, factory: BackstopClientFactory
    ) -> None:
        """The regression the old scope-level semaphore couldn't catch.

        When the gate was held by the client's context manager rather than by each request, a
        single client that gathered N requests put all N on the wire while holding one slot —
        so `search_by_email`'s three-field fan-out multiplied straight through the limit.
        """
        tracker = _InFlightTracker()
        respx.get(f"{_BASE_URL}/system-info").mock(side_effect=tracker.handle)
        client = factory.for_credential(_credential(username="fanout.user"))

        async def fan_out() -> list[httpx.Response]:
            return await asyncio.gather(
                *(client.raw_request("GET", "/system-info") for _ in range(12))
            )

        task = asyncio.create_task(fan_out())
        await asyncio.sleep(0.05)

        assert tracker.max_in_flight == 5

        tracker.release.set()
        await task
        assert tracker.max_in_flight == 5

    @pytest.mark.asyncio
    @respx.mock
    async def test_different_usernames_have_independent_gates(
        self, factory: BackstopClientFactory
    ) -> None:
        tracker = _InFlightTracker()
        respx.get(f"{_BASE_URL}/system-info").mock(side_effect=tracker.handle)

        async def call(username: str) -> httpx.Response:
            return await factory.for_credential(_credential(username=username)).raw_request(
                "GET", "/system-info"
            )

        tasks = [asyncio.create_task(call("user.a")) for _ in range(5)]
        tasks += [asyncio.create_task(call("user.b")) for _ in range(5)]
        await asyncio.sleep(0.05)

        assert tracker.max_in_flight == 10
        assert tracker.in_flight == 10

        tracker.release.set()
        await asyncio.gather(*tasks)

    @pytest.mark.asyncio
    @respx.mock
    async def test_gate_is_not_held_across_unrelated_awaits(
        self, factory: BackstopClientFactory
    ) -> None:
        """A client can be held across a long pause (e.g. an elicitation prompt) for free.

        Under the old design the slot was taken for the lifetime of the `async with`, so five
        users awaiting a prompt starved themselves out of Backstop entirely.
        """
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(200, json={}))
        cred = _credential(username="patient.user")
        clients = [factory.for_credential(cred) for _ in range(10)]

        # All ten clients exist simultaneously and none has consumed a slot yet.
        results = await asyncio.gather(
            *(client.raw_request("GET", "/system-info") for client in clients)
        )

        assert len(results) == 10


class TestGateRegistryEviction:
    @pytest.mark.asyncio
    @respx.mock
    async def test_idle_gates_are_evicted_once_over_capacity(self) -> None:
        """The registry is bounded, so user churn can't grow it without limit."""
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(200, json={}))
        built = client_factory()
        registry = built._gates  # pyright: ignore[reportPrivateUsage]
        registry.max_entries = 4
        try:
            for index in range(10):
                await built.for_credential(_credential(username=f"user.{index}")).raw_request(
                    "GET", "/system-info"
                )
            assert len(registry._gates) <= 4  # pyright: ignore[reportPrivateUsage]
        finally:
            await built.aclose()


class TestRetryIntegration:
    @pytest.mark.asyncio
    @respx.mock
    async def test_succeeds_after_two_concurrency_retries(
        self, factory: BackstopClientFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("backstop_mcp.backstop_client.retry._BACKOFF_INITIAL_SECONDS", 0.01)
        route = respx.get(f"{_BASE_URL}/system-info").mock(
            side_effect=[
                httpx.Response(
                    429,
                    json={
                        "errors": [{"detail": "Concurrency limit exceeded", "code": "concurrency"}]
                    },
                    headers={"Retry-After": "0.01"},
                ),
                httpx.Response(
                    429,
                    json={
                        "errors": [{"detail": "Concurrency limit exceeded", "code": "concurrency"}]
                    },
                    headers={"Retry-After": "0.01"},
                ),
                httpx.Response(200, json={"version": "1.0"}),
            ]
        )

        result = await factory.for_credential(_credential()).raw_request("GET", "/system-info")

        assert result.json() == {"version": "1.0"}
        assert route.call_count == 3

    @pytest.mark.asyncio
    @respx.mock
    async def test_quota_breach_raises_immediately(self, factory: BackstopClientFactory) -> None:
        route = respx.get(f"{_BASE_URL}/system-info").mock(
            return_value=httpx.Response(
                429, json={"errors": [{"detail": "Daily quota exceeded", "code": "day"}]}
            )
        )

        with pytest.raises(BackstopRateLimitError) as exc_info:
            await factory.for_credential(_credential()).raw_request("GET", "/system-info")

        assert exc_info.value.limit_kind == "day"
        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_retry_after_exceeding_ceiling_raises_immediately_without_sleeping(
        self,
    ) -> None:
        route = respx.get(f"{_BASE_URL}/system-info").mock(
            return_value=httpx.Response(
                429,
                json={"errors": [{"detail": "Concurrency limit exceeded", "code": "concurrency"}]},
                headers={"Retry-After": "9999"},
            )
        )
        built = client_factory(max_retry_wait_ms=1_000)

        start = time.monotonic()
        try:
            with pytest.raises(BackstopRateLimitError):
                await built.for_credential(_credential()).raw_request("GET", "/system-info")
        finally:
            await built.aclose()
        elapsed = time.monotonic() - start

        assert route.call_count == 1
        assert elapsed < 0.5

    @pytest.mark.asyncio
    @respx.mock
    async def test_gate_is_released_while_backing_off(
        self, factory: BackstopClientFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A retry must not hold the slot it is waiting for.

        With five concurrent 429-then-200 calls, holding the gate across the backoff sleep would
        deadlock the sixth caller behind sleeping retries rather than letting it through.
        """
        monkeypatch.setattr("backstop_mcp.backstop_client.retry._BACKOFF_INITIAL_SECONDS", 0.01)
        responses = [
            httpx.Response(
                429,
                json={"errors": [{"detail": "Concurrency limit exceeded", "code": "concurrency"}]},
                headers={"Retry-After": "0.01"},
            )
            for _ in range(5)
        ]
        responses += [httpx.Response(200, json={"ok": True}) for _ in range(6)]
        respx.get(f"{_BASE_URL}/system-info").mock(side_effect=responses)
        cred = _credential(username="backoff.user")

        results = await asyncio.wait_for(
            asyncio.gather(
                *(factory.for_credential(cred).raw_request("GET", "/system-info") for _ in range(6))
            ),
            timeout=5,
        )

        assert len(results) == 6


class TestPaginate:
    @pytest.mark.asyncio
    @respx.mock
    async def test_delegates_to_paginate_all_across_multiple_pages(
        self, factory: BackstopClientFactory
    ) -> None:
        respx.get(f"{_BASE_URL}/records").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "data": [{"id": "1"}],
                        "links": {"next": "/records?page[cursor]=abc"},
                    },
                ),
                httpx.Response(200, json={"data": [{"id": "2"}], "links": {"next": None}}),
            ]
        )

        result = await factory.for_credential(_credential()).paginate("/records", schema=_Record)

        assert result == PageResult(
            items=[_Record(id="1"), _Record(id="2")],
            included=[],
            total_count=None,
            truncated=False,
            # Two pages fetched, which is what a tool publishing its cost has to be told.
            request_count=2,
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_parallel_requests_later_pages_by_offset_under_the_gate(
        self, factory: BackstopClientFactory
    ) -> None:
        """`parallel=True` carries the caller's params onto every offset, not just page one."""
        route = respx.get(f"{_BASE_URL}/records").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "data": [{"id": "1"}, {"id": "2"}],
                        "meta": {"totalResourceCount": 5},
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "data": [{"id": "3"}, {"id": "4"}],
                        "meta": {"totalResourceCount": 5},
                    },
                ),
                httpx.Response(
                    200, json={"data": [{"id": "5"}], "meta": {"totalResourceCount": 5}}
                ),
            ]
        )

        result = await factory.for_credential(_credential()).paginate(
            "/records",
            schema=_Record,
            params={"fields": "name"},
            page_size=2,
            max_records=None,
            parallel=True,
        )

        assert [record.id for record in result.items] == ["1", "2", "3", "4", "5"]
        requested = recorded_params(route)
        assert sorted(params["page[offset]"] for params in requested) == ["0", "2", "4"]
        assert {params["fields"] for params in requested} == {"name"}
        assert {params["page[limit]"] for params in requested} == {"2"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_parallel_rewrites_limit_to_the_capped_page_size(
        self, factory: BackstopClientFactory
    ) -> None:
        """A capped first page must not keep the originally requested limit on later offsets."""
        route = respx.get(f"{_BASE_URL}/records").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "data": [{"id": "1"}, {"id": "2"}],
                        "meta": {"totalResourceCount": 5},
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "data": [{"id": "3"}, {"id": "4"}],
                        "meta": {"totalResourceCount": 5},
                    },
                ),
                httpx.Response(
                    200, json={"data": [{"id": "5"}], "meta": {"totalResourceCount": 5}}
                ),
            ]
        )

        result = await factory.for_credential(_credential()).paginate(
            "/records",
            schema=_Record,
            page_size=10,
            max_records=None,
            parallel=True,
        )

        assert [record.id for record in result.items] == ["1", "2", "3", "4", "5"]
        requested = recorded_params(route)
        assert requested[0]["page[limit]"] == "10"
        assert sorted(params["page[offset]"] for params in requested) == ["0", "2", "4"]
        assert {params["page[limit]"] for params in requested[1:]} == {"2"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_paginate_is_serial_by_default(self, factory: BackstopClientFactory) -> None:
        """A true total is not enough on its own — the fan-out has to be asked for."""
        route = respx.get(f"{_BASE_URL}/records").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "data": [{"id": "1"}],
                        "meta": {"totalResourceCount": 2},
                        "links": {"next": "/records?page[offset]=1"},
                    },
                ),
                httpx.Response(200, json={"data": [{"id": "2"}], "links": {"next": None}}),
            ]
        )

        result = await factory.for_credential(_credential()).paginate(
            "/records", schema=_Record, page_size=1, max_records=None
        )

        assert [record.id for record in result.items] == ["1", "2"]
        assert recorded_params(route)[1]["page[offset]"] == "1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_first_page_carries_swagger_documented_page_params(
        self, factory: BackstopClientFactory
    ) -> None:
        """`page[limit]` / `page[offset]`, per the Backstop swagger.

        The old `page[size]` was a guess. Backstop ignores an unknown query param, so the
        symptom was silent: pagination still worked, but the report page-size cap did nothing.
        """
        route = respx.get(f"{_BASE_URL}/records").mock(
            return_value=httpx.Response(200, json={"data": [], "links": {}})
        )

        await factory.for_credential(_credential()).paginate("/records", schema=_Record)

        params = route.calls.last.request.url.params
        assert params["page[limit]"] == str(BackstopConfig().default_page_size)
        assert params["page[offset]"] == "0"

    @pytest.mark.asyncio
    @respx.mock
    async def test_report_paths_default_to_the_report_page_size(
        self, factory: BackstopClientFactory
    ) -> None:
        route = respx.get(f"{_BASE_URL}/reports").mock(
            return_value=httpx.Response(200, json={"data": [], "links": {}})
        )

        await factory.for_credential(_credential()).paginate("/reports", schema=_Record)

        assert route.calls.last.request.url.params["page[limit]"] == str(
            BackstopConfig().report_page_size
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_page_param_names_come_from_config(self) -> None:
        route = respx.get(f"{_BASE_URL}/records").mock(
            return_value=httpx.Response(200, json={"data": [], "links": {}})
        )
        built = client_factory(page_limit_param="limit", page_offset_param="offset")
        try:
            await built.for_credential(_credential()).paginate(
                "/records", schema=_Record, page_size=25
            )
        finally:
            await built.aclose()

        params = route.calls.last.request.url.params
        assert params["limit"] == "25"
        assert params["offset"] == "0"
        assert "page[limit]" not in params

    @pytest.mark.asyncio
    @respx.mock
    async def test_explicit_params_are_not_overridden(self, factory: BackstopClientFactory) -> None:
        route = respx.get(f"{_BASE_URL}/records").mock(
            return_value=httpx.Response(200, json={"data": [], "links": {}})
        )

        await factory.for_credential(_credential()).paginate(
            "/records",
            schema=_Record,
            params={"page[limit]": 3, "page[offset]": 9},
        )

        params = route.calls.last.request.url.params
        assert params["page[limit]"] == "3"
        assert params["page[offset]"] == "9"

    @pytest.mark.asyncio
    @respx.mock
    async def test_max_records_none_walks_the_whole_chain(
        self, factory: BackstopClientFactory
    ) -> None:
        respx.get(f"{_BASE_URL}/records").mock(
            side_effect=[
                httpx.Response(
                    200, json={"data": [{"id": "1"}], "links": {"next": "/records?p=2"}}
                ),
                httpx.Response(
                    200, json={"data": [{"id": "2"}], "links": {"next": "/records?p=3"}}
                ),
                httpx.Response(200, json={"data": [{"id": "3"}], "links": {}}),
            ]
        )

        result = await factory.for_credential(_credential()).paginate(
            "/records", schema=_Record, max_records=None
        )

        assert [item.id for item in result.items] == ["1", "2", "3"]
        assert result.truncated is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_accumulates_and_dedupes_included_resources(
        self, factory: BackstopClientFactory
    ) -> None:
        """`?include=` lands in the top-level `included` array, which used to be dropped."""
        respx.get(f"{_BASE_URL}/records").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "data": [{"id": "1"}],
                        "included": [{"type": "lov-system-sets", "id": "9"}],
                        "links": {"next": "/records?p=2"},
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "data": [{"id": "2"}],
                        # Repeated on this page too — JSON:API does that, and it must not
                        # produce a duplicate.
                        "included": [
                            {"type": "lov-system-sets", "id": "9"},
                            {"type": "lov-system-sets", "id": "10"},
                        ],
                        "links": {},
                    },
                ),
            ]
        )

        result = await factory.for_credential(_credential()).paginate("/records", schema=_Record)

        assert [item["id"] for item in result.included] == ["9", "10"]


class TestFetchPage:
    """`fetch_page` returns exactly one parsed page — no `links.next` walk."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_items_included_total_count_and_next_path(
        self, factory: BackstopClientFactory
    ) -> None:
        respx.get(f"{_BASE_URL}/records").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [{"id": "1"}, {"id": "2"}],
                    "included": [{"type": "lov-system-sets", "id": "9"}],
                    "links": {"next": "/records?page[offset]=25"},
                    "meta": {"totalResourceCount": 42},
                },
            )
        )

        result = await factory.for_credential(_credential()).fetch_page("/records", schema=_Record)

        assert result == SinglePage(
            items=[_Record(id="1"), _Record(id="2")],
            included=[{"type": "lov-system-sets", "id": "9"}],
            total_count=42,
            next_path="/records?page[offset]=25",
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_defaults_page_size_and_zero_offset(self, factory: BackstopClientFactory) -> None:
        route = respx.get(f"{_BASE_URL}/records").mock(
            return_value=httpx.Response(200, json={"data": [], "links": {}})
        )

        await factory.for_credential(_credential()).fetch_page("/records", schema=_Record)

        params = route.calls.last.request.url.params
        assert params["page[limit]"] == str(BackstopConfig().default_page_size)
        assert params["page[offset]"] == "0"

    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_caller_supplied_page_size_and_offset(
        self, factory: BackstopClientFactory
    ) -> None:
        route = respx.get(f"{_BASE_URL}/records").mock(
            return_value=httpx.Response(200, json={"data": [], "links": {}})
        )

        await factory.for_credential(_credential()).fetch_page(
            "/records", schema=_Record, page_size=25, offset=50
        )

        params = route.calls.last.request.url.params
        assert params["page[limit]"] == "25"
        assert params["page[offset]"] == "50"

    @pytest.mark.asyncio
    @respx.mock
    async def test_report_paths_default_to_the_report_page_size(
        self, factory: BackstopClientFactory
    ) -> None:
        route = respx.get(f"{_BASE_URL}/reports").mock(
            return_value=httpx.Response(200, json={"data": [], "links": {}})
        )

        await factory.for_credential(_credential()).fetch_page("/reports", schema=_Record)

        assert route.calls.last.request.url.params["page[limit]"] == str(
            BackstopConfig().report_page_size
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_page_size_and_offset_override_caller_supplied_params(
        self, factory: BackstopClientFactory
    ) -> None:
        """Unlike `.paginate()`, `fetch_page` always drives limit/offset from its own args —
        there's no "first page vs later pages" split, so an explicit `page_size`/`offset`
        always wins over whatever a caller passed in `params`.
        """
        route = respx.get(f"{_BASE_URL}/records").mock(
            return_value=httpx.Response(200, json={"data": [], "links": {}})
        )

        await factory.for_credential(_credential()).fetch_page(
            "/records",
            schema=_Record,
            params={"page[limit]": 999, "page[offset]": 999},
            page_size=10,
            offset=20,
        )

        params = route.calls.last.request.url.params
        assert params["page[limit]"] == "10"
        assert params["page[offset]"] == "20"

    @pytest.mark.asyncio
    @respx.mock
    async def test_page_param_names_come_from_config(self) -> None:
        route = respx.get(f"{_BASE_URL}/records").mock(
            return_value=httpx.Response(200, json={"data": [], "links": {}})
        )
        built = client_factory(page_limit_param="limit", page_offset_param="offset")
        try:
            await built.for_credential(_credential()).fetch_page(
                "/records", schema=_Record, page_size=25, offset=50
            )
        finally:
            await built.aclose()

        params = route.calls.last.request.url.params
        assert params["limit"] == "25"
        assert params["offset"] == "50"
        assert "page[limit]" not in params

    @pytest.mark.asyncio
    @respx.mock
    async def test_malformed_item_raises_schema_error(self, factory: BackstopClientFactory) -> None:
        respx.get(f"{_BASE_URL}/records").mock(
            return_value=httpx.Response(200, json={"data": [{"not_id": "1"}], "links": {}})
        )

        with pytest.raises(BackstopResponseSchemaError) as exc_info:
            await factory.for_credential(_credential()).fetch_page("/records", schema=_Record)

        assert exc_info.value.path == "/records"
        assert exc_info.value.schema_name == "_Page[_Record]"


class TestUntrustedNextLink:
    @pytest.mark.asyncio
    @respx.mock
    async def test_refuses_to_follow_a_link_to_another_host(
        self, factory: BackstopClientFactory
    ) -> None:
        """`links.next` is upstream-controlled, and every request carries Basic auth."""
        respx.get(f"{_BASE_URL}/records").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"id": "1"}], "links": {"next": "https://evil.example.com/records"}},
            )
        )

        with pytest.raises(BackstopUntrustedUrlError) as exc_info:
            await factory.for_credential(_credential()).paginate("/records", schema=_Record)

        assert exc_info.value.url == "https://evil.example.com/records"
        assert exc_info.value.expected_host == httpx.URL(_BASE_URL).netloc.decode("ascii")

    @pytest.mark.asyncio
    @respx.mock
    async def test_refuses_protocol_relative_link_to_another_host(
        self, factory: BackstopClientFactory
    ) -> None:
        """`//evil...` must not skip host pinning just because it lacks an http(s) scheme."""
        respx.get(f"{_BASE_URL}/records").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"id": "1"}], "links": {"next": "//evil.example.com/records"}},
            )
        )

        with pytest.raises(BackstopUntrustedUrlError) as exc_info:
            await factory.for_credential(_credential()).paginate("/records", schema=_Record)

        assert exc_info.value.url == "https://evil.example.com/records"
        assert exc_info.value.expected_host == httpx.URL(_BASE_URL).netloc.decode("ascii")

    @pytest.mark.asyncio
    @respx.mock
    async def test_refuses_same_host_scheme_downgrade(self, factory: BackstopClientFactory) -> None:
        """`links.next` must not flip https→http on the configured host either."""
        https_base = httpx.URL(_BASE_URL)
        assert https_base.scheme == "https"
        http_next = str(https_base.copy_with(scheme="http")) + "/records"

        respx.get(f"{_BASE_URL}/records").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"id": "1"}], "links": {"next": http_next}},
            )
        )

        with pytest.raises(BackstopUntrustedUrlError) as exc_info:
            await factory.for_credential(_credential()).paginate("/records", schema=_Record)

        assert exc_info.value.url == http_next

    @pytest.mark.asyncio
    @respx.mock
    async def test_follows_an_absolute_link_to_the_configured_host(
        self, factory: BackstopClientFactory
    ) -> None:
        respx.get(f"{_BASE_URL}/records").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={"data": [{"id": "1"}], "links": {"next": f"{_BASE_URL}/records?p=2"}},
                ),
                httpx.Response(200, json={"data": [{"id": "2"}], "links": {}}),
            ]
        )

        result = await factory.for_credential(_credential()).paginate("/records", schema=_Record)

        assert [item.id for item in result.items] == ["1", "2"]


class TestSchemaAwareDeserialization:
    """`get`/`post`/`patch`/`delete` all funnel through the same `deserialize` helper, so each
    verb gets matching-body and mismatch cases for a required `schema`.
    """

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_with_schema_returns_parsed_model(
        self, factory: BackstopClientFactory
    ) -> None:
        respx.get(f"{_BASE_URL}/widgets/1").mock(
            return_value=httpx.Response(200, json={"id": "1", "label": "Widget One"})
        )

        result = await factory.for_credential(_credential()).get("/widgets/1", schema=_Widget)

        assert isinstance(result, _Widget)
        assert result.id == "1"
        assert result.label == "Widget One"

    @pytest.mark.asyncio
    @respx.mock
    async def test_post_with_schema_returns_parsed_model(
        self, factory: BackstopClientFactory
    ) -> None:
        respx.post(f"{_BASE_URL}/widgets").mock(
            return_value=httpx.Response(200, json={"id": "1", "label": "Widget One"})
        )

        result = await factory.for_credential(_credential()).post("/widgets", schema=_Widget)

        assert isinstance(result, _Widget)
        assert result.id == "1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_patch_with_schema_returns_parsed_model(
        self, factory: BackstopClientFactory
    ) -> None:
        respx.patch(f"{_BASE_URL}/widgets/1").mock(
            return_value=httpx.Response(200, json={"id": "1", "label": "Widget One"})
        )

        result = await factory.for_credential(_credential()).patch("/widgets/1", schema=_Widget)

        assert isinstance(result, _Widget)
        assert result.id == "1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_delete_with_schema_returns_parsed_model(
        self, factory: BackstopClientFactory
    ) -> None:
        respx.delete(f"{_BASE_URL}/widgets/1").mock(
            return_value=httpx.Response(200, json={"id": "1", "label": "Widget One"})
        )

        result = await factory.for_credential(_credential()).delete("/widgets/1", schema=_Widget)

        assert isinstance(result, _Widget)
        assert result.id == "1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_with_schema_mismatch_raises_schema_error(
        self, factory: BackstopClientFactory
    ) -> None:
        # Missing the required `label` field.
        respx.get(f"{_BASE_URL}/widgets/1").mock(return_value=httpx.Response(200, json={"id": "1"}))

        with pytest.raises(BackstopResponseSchemaError) as exc_info:
            await factory.for_credential(_credential()).get("/widgets/1", schema=_Widget)

        assert exc_info.value.path == "/widgets/1"
        assert exc_info.value.schema_name == "_Widget"
        assert isinstance(exc_info.value.cause, ValidationError)
        assert exc_info.value.__cause__ is exc_info.value.cause

    @pytest.mark.asyncio
    @respx.mock
    async def test_post_with_schema_mismatch_raises_schema_error(
        self, factory: BackstopClientFactory
    ) -> None:
        # `label` is the wrong type (int, not str).
        respx.post(f"{_BASE_URL}/widgets").mock(
            return_value=httpx.Response(200, json={"id": "1", "label": 123})
        )

        with pytest.raises(BackstopResponseSchemaError) as exc_info:
            await factory.for_credential(_credential()).post("/widgets", schema=_Widget)

        assert exc_info.value.path == "/widgets"
        assert exc_info.value.schema_name == "_Widget"

    @pytest.mark.asyncio
    @respx.mock
    async def test_patch_with_schema_mismatch_raises_schema_error(
        self, factory: BackstopClientFactory
    ) -> None:
        # Missing the required `id` field.
        respx.patch(f"{_BASE_URL}/widgets/1").mock(
            return_value=httpx.Response(200, json={"label": "Widget One"})
        )

        with pytest.raises(BackstopResponseSchemaError) as exc_info:
            await factory.for_credential(_credential()).patch("/widgets/1", schema=_Widget)

        assert exc_info.value.path == "/widgets/1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_delete_with_schema_mismatch_raises_schema_error(
        self, factory: BackstopClientFactory
    ) -> None:
        # `id` is the wrong type (int, not str).
        respx.delete(f"{_BASE_URL}/widgets/1").mock(
            return_value=httpx.Response(200, json={"id": 1, "label": "Widget One"})
        )

        with pytest.raises(BackstopResponseSchemaError) as exc_info:
            await factory.for_credential(_credential()).delete("/widgets/1", schema=_Widget)

        assert exc_info.value.path == "/widgets/1"


class TestPaginateSchemaAwareDeserialization:
    """Typed `paginate` validates every accumulated item against the required `schema`."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_multi_page_walk_parses_every_item(self, factory: BackstopClientFactory) -> None:
        respx.get(f"{_BASE_URL}/records").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "data": [{"id": "1"}, {"id": "2"}],
                        "links": {"next": "/records?page[cursor]=abc"},
                    },
                ),
                httpx.Response(200, json={"data": [{"id": "3"}], "links": {}}),
            ]
        )

        result = await factory.for_credential(_credential()).paginate("/records", schema=_Record)

        assert [item.id for item in result.items] == ["1", "2", "3"]
        assert all(isinstance(item, _Record) for item in result.items)
        assert result.total_count is None
        assert result.truncated is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_mismatch_on_later_page_raises_for_whole_call(
        self, factory: BackstopClientFactory
    ) -> None:
        route = respx.get(f"{_BASE_URL}/records").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={"data": [{"id": "1"}], "links": {"next": "/records?page[cursor]=abc"}},
                ),
                httpx.Response(200, json={"data": [{"not_id": "2"}], "links": {}}),
            ]
        )

        with pytest.raises(BackstopResponseSchemaError) as exc_info:
            await factory.for_credential(_credential()).paginate("/records", schema=_Record)

        assert route.call_count == 2
        assert exc_info.value.path == "/records?page[cursor]=abc"
        assert exc_info.value.schema_name == "_Page[_Record]"


class TestDeleteEmptyBody:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_none_for_204_with_no_body(self, factory: BackstopClientFactory) -> None:
        respx.delete(f"{_BASE_URL}/records/1").mock(return_value=httpx.Response(204))

        result = await factory.for_credential(_credential()).delete("/records/1", schema=_Record)

        assert result is None


class TestVerifyCredential:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_true_on_200(self, factory: BackstopClientFactory) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(200, json={}))

        assert await factory.verify_credential("bob.smith", "token") is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_false_on_401(self, factory: BackstopClientFactory) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(401))

        assert await factory.verify_credential("bob.smith", "wrong-token") is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_false_on_403(self, factory: BackstopClientFactory) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(403))

        assert await factory.verify_credential("bob.smith", "wrong-token") is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_unreachable_on_5xx(self, factory: BackstopClientFactory) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(503))

        with pytest.raises(BackstopUnreachableError):
            await factory.verify_credential("bob.smith", "token")

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_unreachable_on_network_error(
        self, factory: BackstopClientFactory
    ) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(side_effect=httpx.ConnectError("boom"))

        with pytest.raises(BackstopUnreachableError):
            await factory.verify_credential("bob.smith", "token")

    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_basic_auth_and_token_header(self, factory: BackstopClientFactory) -> None:
        route = respx.get(f"{_BASE_URL}/system-info").mock(
            return_value=httpx.Response(200, json={})
        )

        await factory.verify_credential("bob.smith", "p@55W0rd321!")

        assert route.called
        sent_request = route.calls.last.request
        assert sent_request.headers["authorization"] == _BASIC_AUTH
        assert sent_request.headers["token"] == "true"
