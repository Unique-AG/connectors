import asyncio
import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import Self

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.opportunities.api_responses import OpportunityStageAttributes
from backstop_mcp.features.opportunities.fetch_opportunity_stages import fetch_opportunity_stages
from backstop_mcp.features.opportunities.internal_dto import OpportunityStageDto
from backstop_mcp.timed_gate import TimedGate

logger = logging.getLogger(__name__)

# How long a failed fetch is remembered before Backstop is tried again. Long enough that a burst
# of tool calls against a down instance costs one round-trip rather than one each, short enough
# that a recovered instance is picked up without an operator waiting on the TTL.
_FAILURE_COOLDOWN = timedelta(seconds=30)


class OpportunityStagesServiceV2:
    """Process-wide opportunity-stage vocabulary, refetched when the TTL lapses.

    Exists because an opportunity's stage history is thin — an effective date plus a stage
    pointer — and only some of the stages it points at arrive in the response's `included`
    array. The rest are named from here.

    Deliberately simpler than `CustomFieldsService`: no in-flight pin, no serve-stale path. That
    catalog is 3,274 definitions and 6.15 s unfiltered, so refetching it is expensive enough to be
    worth softening a failure; this vocabulary is seven rows in one page, and a stage history
    that silently loses half its entries reads as complete when it isn't. So a failed fetch
    propagates and the caller fails with it.

    A failure is remembered for `_FAILURE_COOLDOWN` and re-raised, rather than re-fetched, for
    callers that arrive inside it. Without that, a down Backstop is hit once per `get()` — and
    since every caller queues on the same lock, the Nth of them waits N failure latencies,
    retries and backoff included. The stored exception is raised as-is because the alternative
    during a failure is an empty vocabulary, which reports every stage as unnameable.
    """

    def __init__(self, *, client: BackstopClient, ttl: timedelta) -> None:
        self._client: BackstopClient = client
        self._stages: dict[str, OpportunityStageDto] | None = None
        self._freshness: TimedGate = TimedGate(duration=ttl)
        self._cooldown: TimedGate = TimedGate(duration=_FAILURE_COOLDOWN)
        self._failure: Exception | None = None
        self._lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    def with_ttl_minutes(cls, *, client: BackstopClient, ttl_minutes: int) -> Self:
        return cls(client=client, ttl=timedelta(minutes=ttl_minutes))

    async def get_stage(self, *, stage_id: str) -> OpportunityStageDto | None:
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

    async def get_catalog(self) -> dict[str, OpportunityStageDto]:
        cached = self._stages
        if cached is not None and self._freshness.within():
            return dict(cached)

        async with self._lock:
            # A caller that queued behind the lock while the holder fetched is now fresh.
            cached = self._stages
            if cached is not None and self._freshness.within():
                return dict(cached)

            failure = self._failure
            if failure is not None and self._cooldown.within():
                raise failure

            stages: dict[str, OpportunityStageDto] = {}

            try:
                page = await self._client.paginate(
                    "/opportunity-stages",
                    schema=BackstopApiResource[OpportunityStageAttributes],
                    max_records=None,
                    page_size=100,
                )

                for resource in page.items:
                    stage = OpportunityStageDto.from_resource(resource)
                    if stage is not None:
                        stages[stage.id] = stage
                stages = await fetch_opportunity_stages(self._client)
            except Exception as error:
                self._failure = error
                self._cooldown.mark()
                logger.warning("opportunities.stages.fetch_failed", exc_info=True)
                raise

            self._failure = None
            self._cooldown.clear()
            self._stages = stages
            self._freshness.mark()
            logger.info("opportunities.stages.refreshed", extra={"stages": len(stages)})
            return dict(stages)
