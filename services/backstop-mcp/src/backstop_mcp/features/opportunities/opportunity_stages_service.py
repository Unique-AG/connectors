import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import Self

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.caching import CachedValue
from backstop_mcp.features.opportunities.api_responses import OpportunityStageAttributes
from backstop_mcp.features.opportunities.responses import OpportunityStageResponse
from backstop_mcp.timed_gate import TimedGate

logger = logging.getLogger(__name__)

# How long a failed fetch is remembered before Backstop is tried again. Long enough that a burst
# of tool calls against a down instance costs one round-trip rather than one each, short enough
# that a recovered instance is picked up without an operator waiting on the TTL.
_FAILURE_COOLDOWN = timedelta(seconds=30)


class OpportunityStagesService:
    """Process-wide opportunity-stage vocabulary, refetched when the TTL lapses.

    Exists because an opportunity's stage history is thin — an effective date plus a stage
    pointer — and only some of the stages it points at arrive in the response's `included`
    array. The rest are named from here.

    Composes `CachedValue` with `serve_stale=False`. The custom-field catalog is 3,274
    definitions and 6.15 s unfiltered, so refetching it is expensive enough to be worth
    softening a failure; this vocabulary is seven rows in one page, and a stage history that
    silently loses half its entries reads as complete when it isn't. So a failed fetch
    propagates and the caller fails with it.

    A failure is remembered for `_FAILURE_COOLDOWN` and re-raised, rather than re-fetched, for
    callers that arrive inside it. The in-flight pin already collapses concurrent waiters onto
    one walk; the cooldown is for callers that arrive *after* that walk finishes. The stored
    exception is raised as-is because the alternative during a failure is an empty vocabulary,
    which reports every stage as unnameable.
    """

    def __init__(self, *, client: BackstopClient, ttl: timedelta) -> None:
        self._client: BackstopClient = client
        self._cache: CachedValue[dict[str, OpportunityStageResponse]] = CachedValue(
            ttl=ttl,
            snapshot=dict,
            name="opportunity-stage",
            log_prefix="opportunities.stages",
            serve_stale=False,
        )
        self._cooldown: TimedGate = TimedGate(duration=_FAILURE_COOLDOWN)
        self._failure: Exception | None = None

    @classmethod
    def with_ttl_minutes(cls, *, client: BackstopClient, ttl_minutes: int) -> Self:
        return cls(client=client, ttl=timedelta(minutes=ttl_minutes))

    async def get_stage(self, *, stage_id: str) -> OpportunityStageResponse | None:
        catalog = await self.get_catalog()
        return catalog.get(stage_id, None)

    async def get_stage_name(
        self, *, stage_id: str | None, preloaded_opportunity_id_to_name: Mapping[str, str] | None
    ) -> str | None:
        if stage_id is None:
            return None

        if (
            preloaded_opportunity_id_to_name is not None
            and preloaded_opportunity_id_to_name.get(stage_id, None) is not None
        ):
            return preloaded_opportunity_id_to_name.get(stage_id)

        stage = await self.get_stage(stage_id=stage_id)
        return stage.name if stage else None

    async def get_catalog(self) -> dict[str, OpportunityStageResponse]:
        failure = self._failure
        if failure is not None and self._cooldown.within():
            raise failure

        try:
            catalog, _status = await self._cache.get(self._fetch_stages)
        except Exception as error:
            self._failure = error
            self._cooldown.mark()
            logger.warning("opportunities.stages.fetch_failed", exc_info=True)
            raise

        self._failure = None
        self._cooldown.clear()
        return catalog

    async def _fetch_stages(self) -> dict[str, OpportunityStageResponse]:
        page = await self._client.paginate(
            "/opportunity-stages",
            schema=BackstopApiResource[OpportunityStageAttributes],
            max_records=None,
            page_size=100,
        )
        stages: dict[str, OpportunityStageResponse] = {}
        for resource in page.items:
            stage = OpportunityStageResponse.from_resource(resource)
            if stage is not None:
                stages[stage.id] = stage
        return stages
