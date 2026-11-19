from mcp_observability import traced

from world_check_mcp.contexts.lookups import forget_template_if_rejected
from world_check_mcp.contexts.lookups import screening_lookups
from world_check_mcp.contexts.passport.errors import PassportError
from world_check_mcp.contexts.passport.models import Passport
from world_check_mcp.contexts.passport.models import PassportCheck
from world_check_mcp.contexts.passport.payload import passport_arguments
from world_check_mcp.contexts.screening import derived_case_id
from world_check_mcp.contexts.screening import field_parts
from world_check_mcp.contexts.screening import FieldValue
from world_check_mcp.contexts.screening import match_from_result
from world_check_mcp.contexts.screening import refuse_existing_case
from world_check_mcp.contexts.screening import ScreeningError
from world_check_mcp.contexts.screening import watchlist_results
from world_check_mcp.persistence import Cache
from world_check_mcp.upstream import SAVE_AND_SCREEN
from world_check_mcp.upstream import Upstream
from world_check_mcp.upstream import UpstreamError


@traced(
    arguments=("group_id", "include_watchlist", "limit"),
    result=lambda r: {
        "passport_matches": len(r.passport_matches),
        "watchlist_matches": len(r.watchlist_matches),
    },
)
async def passport_check(
    *,
    upstream: Upstream,
    cache: Cache,
    passport: Passport,
    group_id: str,
    case_id: str | None = None,
    name: str | None = None,
    include_watchlist: bool = True,
    secondary_fields: list[FieldValue] | None = None,
    custom_fields: list[FieldValue] | None = None,
    limit: int = 20,
) -> PassportCheck:
    """Create a Passport Check case and screen it. This does not record a verification decision."""
    effective_case_id = case_id or derived_case_id(
        "PASSPORT_CHECK",
        group_id,
        passport.document_type,
        passport.identification_number,
        passport.issuing_state,
        passport.nationality,
        passport.date_of_birth,
        passport.date_of_expiry,
        passport.gender,
        passport.given_name,
        passport.last_name,
        name or f"{passport.given_name} {passport.last_name}",
        str(include_watchlist),
        *field_parts(fields=secondary_fields),
        *field_parts(fields=custom_fields),
    )
    try:
        await refuse_existing_case(
            upstream=upstream, case_id=effective_case_id, chosen=case_id is not None
        )
    except ScreeningError as error:
        raise PassportError(str(error)) from error
    lookups = await screening_lookups(upstream=upstream, cache=cache, group_id=group_id)
    try:
        arguments = passport_arguments(
            passport=passport,
            name=name or f"{passport.given_name} {passport.last_name}",
            group_id=group_id,
            template=lookups.template,
            countries=lookups.countries,
            nationalities=lookups.nationalities,
            case_id=effective_case_id,
            include_watchlist=include_watchlist,
            secondary_fields=list(secondary_fields or []),
            custom_fields=list(custom_fields or []),
        )
    except ScreeningError as error:
        raise PassportError(str(error)) from error
    try:
        saved = await upstream.call_untyped(SAVE_AND_SCREEN, **arguments)
    except UpstreamError as error:
        await forget_template_if_rejected(cache=cache, group_id=group_id, error=error)
        raise
    if not saved.case_system_id:
        raise PassportError(
            "LSEG completed the passport check but returned no caseSystemId. "
            "Inspect the case before retrying."
        )
    watchlist = watchlist_results(saved.results)
    passport_results = [item for item in saved.results if item.provider_type == "PASSPORT_CHECK"]
    return PassportCheck(
        case_id=saved.case_id,
        case_system_id=saved.case_system_id,
        name=saved.name,
        group_id=saved.group_id,
        passport_matches=[match_from_result(item=item) for item in passport_results],
        watchlist_matches=[match_from_result(item=item) for item in watchlist[:limit]],
        watchlist_truncated=len(watchlist) > limit,
    )
