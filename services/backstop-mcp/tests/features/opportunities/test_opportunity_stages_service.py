import asyncio
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from backstop_mcp.backstop_client import BackstopClient, BackstopClientFactory
from backstop_mcp.features.opportunities import OpportunityStagesService
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


def _service(client: BackstopClient, *, ttl_minutes: int = 60) -> OpportunityStagesService:
    return OpportunityStagesService.with_ttl_minutes(client=client, ttl_minutes=ttl_minutes)


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


def _two_type_stages_page() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                {
                    "id": "s-opp",
                    "type": "opportunity-stages",
                    "attributes": {"name": "Prospect", "closed": False},
                    "relationships": {
                        "opportunityTypes": {"data": [{"type": "entity-types", "id": "16"}]}
                    },
                },
                {
                    "id": "s-other",
                    "type": "opportunity-stages",
                    "attributes": {"name": "Other Pipe", "closed": False},
                    "relationships": {
                        "opportunityTypes": {"data": [{"type": "entity-types", "id": "99"}]}
                    },
                },
            ],
            "links": {"next": None},
        },
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
    service._cache._freshness.mark(past)  # pyright: ignore[reportPrivateUsage]


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

        stages = await _service(clients(base_url)).get_catalog()

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
        """`deletable` and `numberOfOpportunities` are on the wire, not in scope.

        `extra="ignore"` dropping the wrong key is the failure mode worth catching.
        `probability` is modelled: Closed omits the key and reads as None.
        """
        base_url = f"{BASE_URL}/stages-extra-attributes"
        respx.get(f"{base_url}/opportunity-stages").mock(
            return_value=_stages_response(*LIVE_STAGES)
        )

        stages = await _service(clients(base_url)).get_catalog()

        dumped = stages["42482"].model_dump()
        assert "deletable" not in dumped
        assert "numberOfOpportunities" not in dumped
        assert dumped["probability"] == 0.3
        assert stages["96018"].probability is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_opportunity_types_are_side_loaded(self, clients: ClientBuilder) -> None:
        """Two entity types on the wire: a stage can be scoped to a subset of them."""
        base_url = f"{BASE_URL}/stages-two-types"
        route = respx.get(f"{base_url}/opportunity-stages").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "s-opp",
                            "type": "opportunity-stages",
                            "attributes": {"name": "Prospect", "closed": False, "probability": 0.1},
                            "relationships": {
                                "opportunityTypes": {"data": [{"type": "entity-types", "id": "16"}]}
                            },
                        },
                        {
                            "id": "s-other",
                            "type": "opportunity-stages",
                            "attributes": {"name": "Other Pipe", "closed": False},
                            "relationships": {
                                "opportunityTypes": {"data": [{"type": "entity-types", "id": "99"}]}
                            },
                        },
                    ],
                    "included": [
                        {
                            "id": "16",
                            "type": "entity-types",
                            "attributes": {"name": "Opportunity"},
                        },
                        {"id": "99", "type": "entity-types", "attributes": {"name": "Other"}},
                    ],
                    "meta": {"totalResourceCount": 2},
                    "links": {"next": None},
                },
            )
        )

        stages = await _service(clients(base_url)).get_catalog()

        assert route.calls.last.request.url.params["include"] == "opportunityTypes"
        assert stages["s-opp"].opportunity_type_ids == ("16",)
        assert stages["s-other"].opportunity_type_ids == ("99",)

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

        stages = await _service(clients(base_url)).get_catalog()

        assert list(stages) == ["1"]


class TestFindByStageName:
    @pytest.mark.asyncio
    @respx.mock
    async def test_matches_casefold(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/stages-find-name"
        respx.get(f"{base_url}/opportunity-stages").mock(
            return_value=_stages_response(*LIVE_STAGES)
        )

        stage = await _service(clients(base_url)).find_by_stage_name(name="idd")

        assert stage.id == "42482"
        assert stage.name == "IDD"

    @pytest.mark.asyncio
    @respx.mock
    async def test_rejects_an_unknown_name(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/stages-find-unknown"
        respx.get(f"{base_url}/opportunity-stages").mock(
            return_value=_stages_response(*LIVE_STAGES)
        )

        with pytest.raises(ToolError, match="Available stages:.*IDD"):
            await _service(clients(base_url)).find_by_stage_name(name="Not A Stage")

    @pytest.mark.asyncio
    @respx.mock
    async def test_rejects_a_duplicate_name(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/stages-find-dup"
        respx.get(f"{base_url}/opportunity-stages").mock(
            return_value=_stages_response(
                {"id": "a", "name": "Prospect", "closed": False},
                {"id": "b", "name": "Prospect", "closed": False},
            )
        )

        with pytest.raises(ToolError, match="more than one stage"):
            await _service(clients(base_url)).find_by_stage_name(name="Prospect")

    @pytest.mark.asyncio
    @respx.mock
    async def test_scopes_to_entity_type(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/stages-find-scope"
        respx.get(f"{base_url}/opportunity-stages").mock(return_value=_two_type_stages_page())
        service = _service(clients(base_url))

        accepted = await service.find_by_stage_name(name="Prospect", entity_type_id="16")
        assert accepted.id == "s-opp"
        with pytest.raises(ToolError, match="entity type 16"):
            await service.find_by_stage_name(name="Other Pipe", entity_type_id="16")

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_stage_with_no_type_ids_is_valid_for_every_type(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/stages-find-unscoped"
        respx.get(f"{base_url}/opportunity-stages").mock(
            return_value=_stages_response({"id": "s-all", "name": "Prospect", "closed": False})
        )

        stage = await _service(clients(base_url)).find_by_stage_name(
            name="Prospect", entity_type_id="16"
        )

        assert stage.id == "s-all"

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_name_lists_only_stages_valid_for_the_entity_type(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/stages-find-available"
        respx.get(f"{base_url}/opportunity-stages").mock(return_value=_two_type_stages_page())

        with pytest.raises(ToolError, match="Available stages: Prospect") as raised:
            await _service(clients(base_url)).find_by_stage_name(
                name="Not A Stage", entity_type_id="16"
            )

        assert "Other Pipe" not in str(raised.value)


class TestInMemoryTtl:
    @pytest.mark.asyncio
    @respx.mock
    async def test_second_get_within_ttl_does_not_call_backstop(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/stages-ttl-fresh"
        service = _service(clients(base_url))
        route = respx.get(f"{base_url}/opportunity-stages").mock(
            return_value=_stages_response(*LIVE_STAGES)
        )

        first = await service.get_catalog()
        second = await service.get_catalog()

        assert route.call_count == 1
        assert first == second

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_past_ttl_fetches_again(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/stages-ttl-expired"
        service = _service(clients(base_url))
        route = respx.get(f"{base_url}/opportunity-stages").mock(
            side_effect=[
                _stages_response({"id": "1", "name": "Prospect", "sortOrder": 1, "closed": False}),
                _stages_response(
                    {"id": "1", "name": "Prospect", "sortOrder": 1, "closed": False},
                    {"id": "2", "name": "Renamed", "sortOrder": 2, "closed": True},
                ),
            ]
        )

        await service.get_catalog()
        _age_past_ttl(service)
        stages = await service.get_catalog()

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
        service = _service(clients(base_url))

        fetch_started = asyncio.Event()
        release_fetch = asyncio.Event()

        async def blocked_stages(_request: httpx.Request) -> httpx.Response:
            fetch_started.set()
            await release_fetch.wait()
            return _stages_response(*LIVE_STAGES)

        route = respx.get(f"{base_url}/opportunity-stages").mock(side_effect=blocked_stages)

        results = await asyncio.gather(
            service.get_catalog(),
            service.get_catalog(),
            service.get_catalog(),
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
        service = _service(clients(base_url))
        respx.get(f"{base_url}/opportunity-stages").mock(
            return_value=_stages_response(*LIVE_STAGES)
        )

        first = await service.get_catalog()
        del first["96018"]
        second = await service.get_catalog()

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
            await _service(clients(base_url)).get_catalog()

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_failure_inside_the_cooldown_reraises_without_a_second_request(
        self, clients: ClientBuilder
    ) -> None:
        """The stored failure is re-raised, not softened into an empty vocabulary."""
        base_url = f"{BASE_URL}/stages-cooldown"
        service = _service(clients(base_url))
        route = respx.get(f"{base_url}/opportunity-stages").mock(
            side_effect=[
                httpx.ConnectError("backstop down"),
                _stages_response(*LIVE_STAGES),
            ]
        )

        with pytest.raises(httpx.ConnectError):
            await service.get_catalog()
        with pytest.raises(httpx.ConnectError):
            await service.get_catalog()

        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_failure_past_the_cooldown_is_retried(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/stages-cooldown-expired"
        service = _service(clients(base_url))
        route = respx.get(f"{base_url}/opportunity-stages").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        with pytest.raises(httpx.ConnectError):
            await service.get_catalog()
        _age_past_failure_cooldown(service)
        with pytest.raises(httpx.ConnectError):
            await service.get_catalog()

        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_success_after_a_failure_clears_the_failure(
        self, clients: ClientBuilder
    ) -> None:
        """A failure must not cache an empty vocabulary, nor outlive the fetch that recovers."""
        base_url = f"{BASE_URL}/stages-failure-then-success"
        service = _service(clients(base_url))
        route = respx.get(f"{base_url}/opportunity-stages").mock(
            side_effect=[
                httpx.ConnectError("backstop down"),
                _stages_response(*LIVE_STAGES),
            ]
        )

        with pytest.raises(httpx.ConnectError):
            await service.get_catalog()
        _age_past_failure_cooldown(service)
        stages = await service.get_catalog()

        assert route.call_count == 2
        assert len(stages) == 7
        assert service._failure is None  # pyright: ignore[reportPrivateUsage]
        assert service._cooldown.marked_at is None  # pyright: ignore[reportPrivateUsage]
