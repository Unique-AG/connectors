from world_check_mcp.contexts.screening.errors import ScreeningError
from world_check_mcp.contexts.screening.models import ScreeningMatch
from world_check_mcp.contexts.screening.models import ScreeningOutcome
from world_check_mcp.upstream import ResultWire
from world_check_mcp.upstream import ScreenedCaseWire


def outcome(*, screened: ScreenedCaseWire, limit: int) -> ScreeningOutcome:
    if not screened.case_system_id:
        raise ScreeningError(
            "LSEG completed the screening request but returned no caseSystemId. "
            "Inspect the case before retrying."
        )
    watchlist = [item for item in screened.results if item.provider_type != "PASSPORT_CHECK"]
    passport = [item for item in screened.results if item.provider_type == "PASSPORT_CHECK"]
    return ScreeningOutcome(
        case_id=screened.case_id,
        case_system_id=screened.case_system_id,
        name=screened.name,
        entity_type=screened.entity_type,
        group_id=screened.group_id,
        matches_returned=len(screened.results),
        watchlist_matches=[match_from_result(item=item) for item in watchlist[:limit]],
        watchlist_truncated=len(watchlist) > limit,
        passport_matches=[match_from_result(item=item) for item in passport[:limit]],
    )


def match_from_result(*, item: ResultWire) -> ScreeningMatch:
    return ScreeningMatch(
        result_id=item.result_id,
        reference_id=item.reference_id,
        provider_type=item.provider_type,
        match_strength=item.match_strength,
        submitted_term=item.submitted_term,
        mrz_line_1=item.mrz_line_1,
        mrz_line_2=item.mrz_line_2,
        mrz_line_3=item.mrz_line_3,
    )
