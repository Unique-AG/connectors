from world_check_mcp.contexts.cases import get_case
from world_check_mcp.contexts.screening.errors import ScreeningError
from world_check_mcp.contexts.screening.models import ScreeningOutcome
from world_check_mcp.contexts.screening.outcome import outcome
from world_check_mcp.upstream import PARTIAL_UPDATE_CASE
from world_check_mcp.upstream import Upstream

_ALLOWED = frozenset({"WATCHLIST", "PASSPORT_CHECK"})


async def rescreen_case(
    *, upstream: Upstream, case: str, delta: bool = False, limit: int = 20
) -> ScreeningOutcome:
    """Rescreen an existing case without editing its fields."""
    found = await get_case(upstream=upstream, case=case)
    providers = found.provider_types
    if not providers or any(provider not in _ALLOWED for provider in providers):
        raise ScreeningError(
            "Rescreening is restricted to WATCHLIST and PASSPORT_CHECK. Media Check is unsupported."
        )
    screened = await upstream.call(
        PARTIAL_UPDATE_CASE,
        caseSystemId=found.case_system_id,
        screen="DELTA_SYNC" if delta else "SYNC",
    )
    return outcome(screened=screened, limit=limit)
