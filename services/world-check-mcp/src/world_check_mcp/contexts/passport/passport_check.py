from world_check_mcp.contexts.passport.errors import PassportError
from world_check_mcp.contexts.passport.models import Passport
from world_check_mcp.contexts.passport.models import PassportCheck
from world_check_mcp.contexts.passport.payload import passport_arguments
from world_check_mcp.contexts.screening import FieldValue
from world_check_mcp.contexts.screening import match_from_result
from world_check_mcp.contexts.screening import refuse_existing_case
from world_check_mcp.upstream import GET_CASE_TEMPLATE_FOR_GROUP
from world_check_mcp.upstream import GET_COUNTRIES
from world_check_mcp.upstream import GET_NATIONALITIES
from world_check_mcp.upstream import SAVE_AND_SCREEN
from world_check_mcp.upstream import Upstream


async def passport_check(
    *,
    upstream: Upstream,
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
    await refuse_existing_case(upstream=upstream, case_id=case_id)
    template = await upstream.call(GET_CASE_TEMPLATE_FOR_GROUP, groupId=group_id)
    countries = await upstream.call(GET_COUNTRIES)
    nationalities = await upstream.call(GET_NATIONALITIES)
    saved = await upstream.call(
        SAVE_AND_SCREEN,
        **passport_arguments(
            passport=passport,
            name=name or f"{passport.given_name} {passport.last_name}",
            group_id=group_id,
            template=template,
            countries=countries.root,
            nationalities=nationalities.root,
            case_id=case_id,
            include_watchlist=include_watchlist,
            secondary_fields=list(secondary_fields or []),
            custom_fields=list(custom_fields or []),
        ),
    )
    if not saved.case_system_id:
        raise PassportError(
            "LSEG completed the passport check but returned no caseSystemId. "
            "Inspect the case before retrying."
        )
    watchlist = [item for item in saved.results if item.provider_type == "WATCHLIST"]
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
