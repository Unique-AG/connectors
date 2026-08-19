import asyncio
import logging
from datetime import timedelta
from typing import Annotated

from pydantic import StringConstraints

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.opportunities.api_responses import OpportunityStageAttributes
from backstop_mcp.features.opportunities.internal_dto import OpportunityStageDto
from backstop_mcp.timed_gate import TimedGate

logger = logging.getLogger(__name__)

_STAGES_PATH = "/opportunity-stages"
_STAGES_PAGE_SIZE = 100

# How long a failed fetch is remembered before Backstop is tried again. Long enough that a burst
# of tool calls against a down instance costs one round-trip rather than one each, short enough
# that a recovered instance is picked up without an operator waiting on the TTL.
_FAILURE_COOLDOWN = timedelta(seconds=30)

_StrippedStr = Annotated[str, StringConstraints(strip_whitespace=True)]


OpportunityStage = OpportunityStageDto


type StageResource = BackstopApiResource[OpportunityStageAttributes]


def stage_from_resource(resource: StageResource) -> OpportunityStage | None:
    """Map one `opportunity-stages` resource onto the vocabulary shape.

    Returns None when `name` is missing — naming a stage is the whole point of this vocabulary,
    so an unnamed row would only masquerade as a resolution.
    """
    name = resource.attributes.name
    if not name:
        return None

    return OpportunityStage(
        id=resource.id,
        name=name,
        closed=bool(resource.attributes.closed),
        sort_order=resource.attributes.sort_order,
    )


async def fetch_opportunity_stages(client: BackstopClient) -> dict[str, OpportunityStage]:
    """Fetch the instance's opportunity-stage vocabulary, keyed by stage id."""
    page = await client.paginate(
        _STAGES_PATH,
        schema=BackstopApiResource[OpportunityStageAttributes],
        max_records=None,
        page_size=_STAGES_PAGE_SIZE,
    )

    stages: dict[str, OpportunityStage] = {}
    for resource in page.items:
        stage = stage_from_resource(resource)
        if stage is not None:
            stages[stage.id] = stage
    return stages


class OpportunityStagesService:
    """Process-wide opportunity-stage vocabulary, refetched when the TTL lapses.

    Exists because an opportunity's stage history is thin — an effective date plus a stage
    pointer — and only some of the stages it points at arrive in the response's `included`
    array. The rest are named from here.

    Deliberately simpler than `CustomFieldsService`: no in-flight pin, no serve-stale path. That
    catalog is ~1000 definitions over many pages, so refetching it is expensive enough to be
    worth softening a failure; this vocabulary is seven rows in one page, and a stage history
    that silently loses half its entries reads as complete when it isn't. So a failed fetch
    propagates and the caller fails with it.

    A failure is remembered for `_FAILURE_COOLDOWN` and re-raised, rather than re-fetched, for
    callers that arrive inside it. Without that, a down Backstop is hit once per `get()` — and
    since every caller queues on the same lock, the Nth of them waits N failure latencies,
    retries and backoff included. The stored exception is raised as-is because the alternative
    during a failure is an empty vocabulary, which reports every stage as unnameable.
    """

    def __init__(self, *, ttl: timedelta) -> None:
        self._stages: dict[str, OpportunityStage] | None = None
        self._freshness: TimedGate = TimedGate(duration=ttl)
        self._cooldown: TimedGate = TimedGate(duration=_FAILURE_COOLDOWN)
        self._failure: Exception | None = None
        self._lock: asyncio.Lock = asyncio.Lock()

    async def get(self, client: BackstopClient) -> dict[str, OpportunityStage]:
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

            try:
                stages = await fetch_opportunity_stages(client)
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


def create_opportunity_stages_service(*, ttl_minutes: int) -> OpportunityStagesService:
    return OpportunityStagesService(ttl=timedelta(minutes=ttl_minutes))
