import asyncio
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient, BackstopClientFactory
from backstop_mcp.features.opportunities.stages import (
    OpportunityStagesService,
    create_opportunity_stages_service,
)
from tests.helpers import BASE_URL, client_factory, credential, resource

type ClientBuilder = Callable[[str], BackstopClient]

# The instance's whole vocabulary, verbatim from `GET /opportunity-stages`: seven rows, with the
# attribute keys each one actually carries — `Closed` has no `probability` key at all, absent
# rather than null. A page is deserialized in one pass, so a required field would fail all seven
# rows over one malformed row; the wire model keeps every field optional instead.
LIVE_STAGES: tuple[dict[str, object], ...] = (
    {"id": "42478", "name": "Prospect", "sortOrder": 1, "closed": False, "probability": 0.05},
    {"id": "42480", "name": "Project", "sortOrder": 2, "closed": False, "probability": 0.1},
    {"id": "42482", "name": "IDD", "sortOrder": 3, "closed": False, "probability": 0.3},
    {
        "id": "85446",
        "name": "Client Approval",
        "sortOrder": 4,
        "closed": False,
        "probability": 0.7,
    },
    {"id": "85444", "name": "Execution", "sortOrder": 5, "closed": False, "probability": 0.9},
    {"id": "96016", "name": "Invested", "sortOrder": 6, "closed": True, "probability": 1.0},
    {"id": "96018", "name": "Closed", "sortOrder": 7, "closed": True},
)

_OPPORTUNITY_COUNTS = {"96016": 299, "96018": 784}


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
        return factory.for_credential(credential("stages-bob"))

    yield make
    for factory in built:
        await factory.aclose()


def _service(*, ttl_minutes: int = 60) -> OpportunityStagesService:
    return create_opportunity_stages_service(ttl_minutes=ttl_minutes)


def _stage_resource(row: dict[str, object]) -> dict[str, object]:
    """One live row as Backstop returns it, with the attributes it does not publish left out."""
    stage_id = str(row["id"])
    name = row.get("name")
    attributes = {key: value for key, value in row.items() if key not in ("id", "name")}
    return resource(
        stage_id,
        "opportunity-stages",
        name=None if name is None else str(name),
        deletable=False,
        numberOfOpportunities=_OPPORTUNITY_COUNTS.get(stage_id, 0),
        **attributes,
    )


def _stages_response(*rows: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [_stage_resource(row) for row in rows],
            "meta": {"totalResourceCount": len(rows)},
            "links": {"next": None},
        },
    )


def _age_past_ttl(service: OpportunityStagesService) -> None:
    past = datetime.now(UTC) - timedelta(minutes=90)
    service._freshness.mark(past)  # pyright: ignore[reportPrivateUsage]


def _age_past_failure_cooldown(service: OpportunityStagesService) -> None:
    past = datetime.now(UTC) - timedelta(minutes=90)
    service._cooldown.mark(past)  # pyright: ignore[reportPrivateUsage]


class TestFetchingTheVocabulary:
    @pytest.mark.asyncio
    @respx.mock
    async def test_every_live_row_is_parsed(self, clients: ClientBuilder) -> None:
        """Including `Closed`, whose `probability` key is absent rather than null."""
        base_url = f"{BASE_URL}/stages-live"
        route = respx.get(f"{base_url}/opportunity-stages").mock(
            return_value=_stages_response(*LIVE_STAGES)
        )

        stages = await _service().get(clients(base_url))

        assert route.calls.last.request.url.params["page[limit]"] == "100"
        assert len(stages) == 7
        in_order = sorted(stages.values(), key=lambda stage: stage.sort_order or 0)
        assert [stage.name for stage in in_order] == [
            "Prospect",
            "Project",
            "IDD",
            "Client Approval",
            "Execution",
            "Invested",
            "Closed",
        ]
        assert stages["96018"].name == "Closed"
        assert stages["96018"].closed is True
        assert stages["96018"].sort_order == 7

    @pytest.mark.asyncio
    @respx.mock
    async def test_unmodelled_wire_attributes_do_not_surface(self, clients: ClientBuilder) -> None:
        """`deletable`, `numberOfOpportunities` and `probability` are on the wire, not in scope.

        `extra="ignore"` dropping the wrong key is the failure mode worth catching.
        """
        base_url = f"{BASE_URL}/stages-extra-attributes"
        respx.get(f"{base_url}/opportunity-stages").mock(
            return_value=_stages_response(*LIVE_STAGES)
        )

        stages = await _service().get(clients(base_url))

        assert set(stages["42482"].model_dump()) == {"id", "name", "closed", "sort_order"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_row_without_a_name_is_dropped(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/stages-unnamed"
        respx.get(f"{base_url}/opportunity-stages").mock(
            return_value=_stages_response(
                {"id": "1", "name": "Prospect", "sortOrder": 1, "closed": False},
                {"id": "2", "sortOrder": 2, "closed": False},
            )
        )

        stages = await _service().get(clients(base_url))

        assert list(stages) == ["1"]


class TestInMemoryTtl:
    @pytest.mark.asyncio
    @respx.mock
    async def test_second_get_within_ttl_does_not_call_backstop(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/stages-ttl-fresh"
        service = _service()
        route = respx.get(f"{base_url}/opportunity-stages").mock(
            return_value=_stages_response(*LIVE_STAGES)
        )

        first = await service.get(clients(base_url))
        second = await service.get(clients(base_url))

        assert route.call_count == 1
        assert first == second

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_past_ttl_fetches_again(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/stages-ttl-expired"
        service = _service()
        route = respx.get(f"{base_url}/opportunity-stages").mock(
            side_effect=[
                _stages_response({"id": "1", "name": "Prospect", "sortOrder": 1, "closed": False}),
                _stages_response(
                    {"id": "1", "name": "Prospect", "sortOrder": 1, "closed": False},
                    {"id": "2", "name": "Renamed", "sortOrder": 2, "closed": True},
                ),
            ]
        )

        await service.get(clients(base_url))
        _age_past_ttl(service)
        stages = await service.get(clients(base_url))

        assert route.call_count == 2
        assert sorted(stages) == ["1", "2"]

    @staticmethod
    async def _join_in_flight(started: asyncio.Event, release: asyncio.Event) -> None:
        """Unblock Backstop only once the sibling gets have had a turn to reach the lock."""
        await started.wait()
        for _ in range(20):
            await asyncio.sleep(0)
        release.set()

    @pytest.mark.asyncio
    @respx.mock
    async def test_concurrent_cold_gets_produce_one_fetch(self, clients: ClientBuilder) -> None:
        """The holder is still inside the fetch when the other two arrive, so only the lock
        can collapse them: the TTL is not marked yet."""
        base_url = f"{BASE_URL}/stages-single-flight"
        service = _service()
        client = clients(base_url)

        fetch_started = asyncio.Event()
        release_fetch = asyncio.Event()

        async def blocked_stages(_request: httpx.Request) -> httpx.Response:
            fetch_started.set()
            await release_fetch.wait()
            return _stages_response(*LIVE_STAGES)

        route = respx.get(f"{base_url}/opportunity-stages").mock(side_effect=blocked_stages)

        results = await asyncio.gather(
            service.get(client),
            service.get(client),
            service.get(client),
            self._join_in_flight(fetch_started, release_fetch),
        )

        assert route.call_count == 1
        for stages in results[:3]:
            assert len(stages) == 7

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_mutated_result_does_not_reach_the_next_caller(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/stages-copy"
        service = _service()
        respx.get(f"{base_url}/opportunity-stages").mock(
            return_value=_stages_response(*LIVE_STAGES)
        )

        first = await service.get(clients(base_url))
        del first["96018"]
        second = await service.get(clients(base_url))

        assert "96018" in second


class TestFailureIsNotAnEmptyVocabulary:
    """Serving nothing would report every stage as unnameable, which reads as an answer."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_failed_fetch_propagates(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/stages-cold-failure"
        respx.get(f"{base_url}/opportunity-stages").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        with pytest.raises(httpx.ConnectError):
            await _service().get(clients(base_url))

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_failure_inside_the_cooldown_reraises_without_a_second_request(
        self, clients: ClientBuilder
    ) -> None:
        """The stored failure is re-raised, not softened into an empty vocabulary."""
        base_url = f"{BASE_URL}/stages-cooldown"
        service = _service()
        route = respx.get(f"{base_url}/opportunity-stages").mock(
            side_effect=[
                httpx.ConnectError("backstop down"),
                _stages_response(*LIVE_STAGES),
            ]
        )

        with pytest.raises(httpx.ConnectError):
            await service.get(clients(base_url))
        with pytest.raises(httpx.ConnectError):
            await service.get(clients(base_url))

        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_failure_past_the_cooldown_is_retried(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/stages-cooldown-expired"
        service = _service()
        route = respx.get(f"{base_url}/opportunity-stages").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        with pytest.raises(httpx.ConnectError):
            await service.get(clients(base_url))
        _age_past_failure_cooldown(service)
        with pytest.raises(httpx.ConnectError):
            await service.get(clients(base_url))

        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_success_after_a_failure_clears_the_failure(
        self, clients: ClientBuilder
    ) -> None:
        """A failure must not cache an empty vocabulary, nor outlive the fetch that recovers."""
        base_url = f"{BASE_URL}/stages-failure-then-success"
        service = _service()
        route = respx.get(f"{base_url}/opportunity-stages").mock(
            side_effect=[
                httpx.ConnectError("backstop down"),
                _stages_response(*LIVE_STAGES),
            ]
        )

        with pytest.raises(httpx.ConnectError):
            await service.get(clients(base_url))
        _age_past_failure_cooldown(service)
        stages = await service.get(clients(base_url))

        assert route.call_count == 2
        assert len(stages) == 7
        assert service._failure is None  # pyright: ignore[reportPrivateUsage]
        assert service._cooldown.marked_at is None  # pyright: ignore[reportPrivateUsage]
