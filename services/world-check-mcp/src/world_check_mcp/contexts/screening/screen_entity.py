from datetime import date

from world_check_mcp.contexts.cases import CaseNotFoundError
from world_check_mcp.contexts.cases import get_case_reference
from world_check_mcp.contexts.screening.errors import ScreeningError
from world_check_mcp.contexts.screening.fields import check_entity
from world_check_mcp.contexts.screening.fields import screening_arguments
from world_check_mcp.contexts.screening.models import EntityType
from world_check_mcp.contexts.screening.models import FieldValue
from world_check_mcp.contexts.screening.models import Gender
from world_check_mcp.contexts.screening.models import ScreeningOutcome
from world_check_mcp.contexts.screening.outcome import outcome
from world_check_mcp.upstream import GET_CASE_TEMPLATE_FOR_GROUP
from world_check_mcp.upstream import GET_COUNTRIES
from world_check_mcp.upstream import GET_NATIONALITIES
from world_check_mcp.upstream import SAVE_AND_SCREEN
from world_check_mcp.upstream import Upstream


async def screen_entity(
    *,
    upstream: Upstream,
    name: str,
    entity_type: EntityType,
    group_id: str,
    case_id: str | None = None,
    dob: date | None = None,
    nationality: str | None = None,
    country_of_residence: str | None = None,
    place_of_birth: str | None = None,
    registered_country: str | None = None,
    gender: Gender | None = None,
    secondary_fields: list[FieldValue] | None = None,
    custom_fields: list[FieldValue] | None = None,
    limit: int = 20,
) -> ScreeningOutcome:
    """Create a WATCHLIST case and screen it synchronously."""
    check_entity(
        entity_type=entity_type,
        dob=dob,
        nationality=nationality,
        country_of_residence=country_of_residence,
        place_of_birth=place_of_birth,
        registered_country=registered_country,
        gender=gender,
        case_id=case_id,
    )
    await _refuse_duplicate(upstream=upstream, case_id=case_id)
    template = await upstream.call(GET_CASE_TEMPLATE_FOR_GROUP, groupId=group_id)
    countries = await upstream.call(GET_COUNTRIES)
    nationalities = await upstream.call(GET_NATIONALITIES)
    saved = await upstream.call(
        SAVE_AND_SCREEN,
        **screening_arguments(
            name=name,
            entity_type=entity_type,
            group_id=group_id,
            template=template,
            countries=countries.root,
            nationalities=nationalities.root,
            case_id=case_id,
            dob=dob,
            nationality=nationality,
            country_of_residence=country_of_residence,
            place_of_birth=place_of_birth,
            registered_country=registered_country,
            gender=gender,
            secondary_fields=list(secondary_fields or []),
            custom_fields=list(custom_fields or []),
        ),
    )
    return outcome(screened=saved, limit=limit)


async def _refuse_duplicate(*, upstream: Upstream, case_id: str | None) -> None:
    if case_id is None:
        return
    try:
        existing = await get_case_reference(upstream=upstream, case_id=case_id)
    except CaseNotFoundError:
        return
    raise ScreeningError(
        f"case_id already exists (case_system_id={existing.case_system_id}). "
        "Use get_case or rescreen_case."
    )
