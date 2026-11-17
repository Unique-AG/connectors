import asyncio

from polixis_mcp.contexts.entities.get_entity_profiles.inputs import KEY_SECTIONS
from polixis_mcp.contexts.entities.get_entity_profiles.inputs import ProfileSection
from polixis_mcp.contexts.entities.get_entity_profiles.outputs import EntityProfile
from polixis_mcp.contexts.entities.get_entity_profiles.outputs import EntityProfiles
from polixis_mcp.contexts.entities.get_entity_profiles.outputs import PositionHeld
from polixis_mcp.contexts.entities.get_entity_profiles.outputs import ProfileAlert
from polixis_mcp.contexts.entities.get_entity_profiles.outputs import SanctionListing
from polixis_mcp.contexts.entities.names import name_record
from polixis_mcp.contexts.formats import dates_by_kind
from polixis_mcp.contexts.formats import partial_date
from polixis_mcp.contexts.formats import unique
from polixis_mcp.contexts.risks import is_hidden_alert
from polixis_mcp.contexts.risks import polixis_flags
from polixis_mcp.upstream import CompletionRequestInput
from polixis_mcp.upstream import GET_PROFILE_FIELDS
from polixis_mcp.upstream import GetProfileFieldsPath
from polixis_mcp.upstream import GetProfileFieldsRequest
from polixis_mcp.upstream import PolixisRejectedError
from polixis_mcp.upstream import Profile
from polixis_mcp.upstream import Upstream
from polixis_mcp.upstream import UpstreamError


async def get_entity_profiles(
    *, upstream: Upstream, pids: list[str], sections: list[ProfileSection] | None
) -> EntityProfiles:
    """One request per entity, all at once, for `sections`, or the key ones when None. An id
    Polixis rejects gets `rejected` rather than failing the others.
    """
    chosen = unique(sections or KEY_SECTIONS)
    try:
        async with asyncio.TaskGroup() as group:
            lookups = [
                group.create_task(_profile(upstream=upstream, pid=pid, sections=chosen))
                for pid in unique(pids)
            ]
    except* UpstreamError as errors:
        raise errors.exceptions[0] from None
    return EntityProfiles(profiles=[lookup.result() for lookup in lookups])


async def _profile(
    *, upstream: Upstream, pid: str, sections: list[ProfileSection]
) -> EntityProfile:
    try:
        profile = await upstream.call(
            GET_PROFILE_FIELDS,
            GetProfileFieldsRequest(
                path=GetProfileFieldsPath(id=pid),
                body=CompletionRequestInput(
                    fields=[_POLIXIS_FIELDS[section] for section in sections]
                ),
            ),
        )
    except PolixisRejectedError as error:
        return EntityProfile(pid=pid, rejected=str(error))
    return _entity_profile(pid=pid, profile=profile, sections=set(sections))


def _names(names: dict[str, list[str]]) -> list[str]:
    """Every name, the English ones first, then the original ones, then any other key's."""
    keys = sorted(names, key=lambda key: (key != "en", key != "original"))
    return unique(name for key in keys for name in names[key])


def _entity_profile(*, pid: str, profile: Profile, sections: set[ProfileSection]) -> EntityProfile:
    mapped = EntityProfile(
        pid=pid,
        names=_names(profile.names or {}),
        name_records=unique(name_record(record) for record in profile.name_records or []),
        identifiers=profile.unis or {},
        countries=profile.countries or {},
        dates=dates_by_kind(profile.dates),
        gender=profile.gender,
        legal_forms=unique(
            entry.en or entry.original for entry in profile.legal_type_entries or []
        ),
        economic_activities=unique(
            entry.en or entry.original for entry in profile.eac_entries or []
        ),
        addresses=unique(profile.addresses or []),
        flags=polixis_flags(profile.flags or []),
        alerts=[
            ProfileAlert(category=alert.category, message=alert.message)
            for alert in profile.alert_list or []
            if alert.message and not is_hidden_alert(alert.category)
        ],
        sanction_statuses=profile.sanction_statuses or {},
        sanctions=[
            SanctionListing(
                list_name=list_name,
                country=record.country,
                status=next(iter((record.details or {}).get("Sanction Status", [])), None),
                details=record.details or {},
            )
            for list_name, records in (profile.sanctions or {}).items()
            for record in records
        ],
        positions=[
            PositionHeld(
                position=position.position,
                institution=position.institution,
                start_date=partial_date(position.start_date),
                end_date=partial_date(position.end_date),
                remark=position.remark,
            )
            for position in profile.positions or []
            if position.position
        ],
    )
    # Every section is mapped above, then the ones not asked for go back to None, so a
    # section Polixis left out reads as empty and one not requested as null.
    return mapped.model_copy(
        update={section: None for section in _POLIXIS_FIELDS if section not in sections}
    )


_POLIXIS_FIELDS: dict[ProfileSection, str] = {
    "names": "names",
    "name_records": "nameRecords",
    "identifiers": "unis",
    "countries": "countries",
    "dates": "dates",
    "gender": "gender",
    "legal_forms": "legalTypeEntries",
    "economic_activities": "eacEntries",
    "addresses": "addresses",
    "flags": "flags",
    "alerts": "alertList",
    "sanction_statuses": "sanctionStatuses",
    "sanctions": "sanctions",
    "positions": "positions",
}
