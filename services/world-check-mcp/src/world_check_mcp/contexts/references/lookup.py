from typing import Literal

from mcp_observability import traced

from world_check_mcp.contexts.references.models import Profile
from world_check_mcp.contexts.references.models import ProviderSummary
from world_check_mcp.contexts.references.models import ReferenceData
from world_check_mcp.contexts.references.models import SearchFilter
from world_check_mcp.upstream import Entity
from world_check_mcp.upstream import GET_API_INFO
from world_check_mcp.upstream import GET_COUNTRIES
from world_check_mcp.upstream import GET_NATIONALITIES
from world_check_mcp.upstream import GET_PROVIDERS
from world_check_mcp.upstream import GET_RECORD
from world_check_mcp.upstream import GET_SEARCH_FILTERS
from world_check_mcp.upstream import GetApiInfoRequest
from world_check_mcp.upstream import GetCountriesRequest
from world_check_mcp.upstream import GetNationalitiesRequest
from world_check_mcp.upstream import GetProvidersRequest
from world_check_mcp.upstream import GetRecordPath
from world_check_mcp.upstream import GetRecordRequest
from world_check_mcp.upstream import GetSearchFiltersRequest
from world_check_mcp.upstream import ProviderDetail
from world_check_mcp.upstream import SearchParameterCollection
from world_check_mcp.upstream import Upstream

ReferenceKind = Literal["countries", "nationalities", "providers", "search_filters", "api_info"]


@traced(arguments=("reference_id",))
async def get_profile(*, upstream: Upstream, reference_id: str) -> Profile:
    """The World-Check record for a match referenceId, not a resultId."""
    record = await upstream.call(GET_RECORD, GetRecordRequest(path=GetRecordPath(id=reference_id)))
    return _profile(record=record)


@traced(arguments=("kind",))
async def get_reference_data(*, upstream: Upstream, kind: ReferenceKind) -> ReferenceData:
    """Countries, nationalities, providers, search filters, or the API version."""
    if kind == "countries":
        countries = await upstream.call(GET_COUNTRIES, GetCountriesRequest())
        return ReferenceData(kind=kind, names_by_code=countries.root)
    if kind == "nationalities":
        nationalities = await upstream.call(GET_NATIONALITIES, GetNationalitiesRequest())
        return ReferenceData(kind=kind, names_by_code=nationalities.root)
    if kind == "providers":
        providers = await upstream.call(GET_PROVIDERS, GetProvidersRequest())
        return ReferenceData(
            kind=kind, providers=[_provider(provider=provider) for provider in providers]
        )
    if kind == "search_filters":
        filters = await upstream.call(GET_SEARCH_FILTERS, GetSearchFiltersRequest())
        return ReferenceData(kind=kind, search_filters=_filters(collection=filters))
    info = await upstream.call(GET_API_INFO, GetApiInfoRequest())
    return ReferenceData(
        kind=kind, api_version=info.version, system_date_time=info.system_date_time
    )


def _profile(*, record: Entity) -> Profile:
    names = [
        part.value
        for detail in record.names.name_details or []
        for part in detail.details or []
        if part.value
    ]
    categories = [category.value for category in record.categories or [] if category.value]
    return Profile(
        reference_id=record.reference_id,
        entity_type=record.entity_type,
        names=names,
        categories=categories,
    )


def _provider(*, provider: ProviderDetail) -> ProviderSummary:
    return ProviderSummary(code=provider.code, identifier=provider.identifier, name=provider.name)


def _filters(*, collection: SearchParameterCollection) -> list[SearchFilter]:
    queries = collection.free_text_parameters or []
    custom = collection.custom_field_parameters or []
    predefined = collection.predefined_parameters or []
    return [
        *[SearchFilter(kind="query", fields=parameter.fields) for parameter in queries],
        *[SearchFilter(kind="custom", fields=parameter.fields) for parameter in custom],
        *[SearchFilter(kind="filter", fields=parameter.fields) for parameter in predefined],
    ]
