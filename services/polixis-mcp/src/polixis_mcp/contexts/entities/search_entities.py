from typing import Literal

from pydantic import BaseModel
from pydantic import Field

from polixis_mcp.contexts.entities.names import display_name
from polixis_mcp.contexts.entities.names import name_record
from polixis_mcp.contexts.entities.names import NameRecordView
from polixis_mcp.contexts.formats import dates_by_kind
from polixis_mcp.contexts.formats import PartialDate
from polixis_mcp.contexts.formats import polixis_date_number
from polixis_mcp.contexts.formats import unique
from polixis_mcp.contexts.freshness import Freshness
from polixis_mcp.contexts.freshness import freshness
from polixis_mcp.contexts.pages import encode_cursor
from polixis_mcp.contexts.pages import PageQuery
from polixis_mcp.contexts.risks import ALERT_TEXTS_DESCRIPTION
from polixis_mcp.contexts.risks import visible_alert_texts
from polixis_mcp.upstream import SEARCH_ENTITIES
from polixis_mcp.upstream import SearchEntitiesRequest
from polixis_mcp.upstream import SearchHit
from polixis_mcp.upstream import SearchRequestInput
from polixis_mcp.upstream import Upstream

EntityType = Literal["ORGANIZATION", "PERSON"]

# A hit lists up to 60 spellings of a name and 20 addresses. The first few tell matches apart;
# `get_entity_profiles` returns them all. The names listed are the typed records, then the
# spellings no record holds, up to this many in all.
_NAMES_LISTED = 10
_ADDRESSES_LISTED = 3


async def search_entities(*, upstream: Upstream, query: EntitySearchQuery) -> EntitySearchResults:
    filters = {
        "entity_type": query.entity_type,
        "countries": [country.lower() for country in query.countries] or None,
        "dates": [polixis_date_number(date) for date in query.dates] or None,
    }
    # The client sends a field set to None as null, so a filter left out is not set at all.
    body = SearchRequestInput.model_validate(
        {
            "name": query.name,
            **{name: value for name, value in filters.items() if value is not None},
            "page": query.page,
            "size": query.page_size,
        }
    )
    response = await upstream.call(SEARCH_ENTITIES, SearchEntitiesRequest(body=body))
    pagination = response.pagination
    has_next = pagination is not None and bool(pagination.has_next)
    return EntitySearchResults(
        results=[match for hit in response.hits or [] if (match := _match(hit=hit)) is not None],
        total_matches=pagination.total_hits if pagination is not None else None,
        next_cursor=(
            encode_cursor(query.model_copy(update={"page": query.page + 1})) if has_next else None
        ),
        freshness=freshness(),
    )


def _match(*, hit: SearchHit) -> EntityMatch | None:
    """None for a hit without a pid, which no other Polixis endpoint can look up."""
    if not hit.pid:
        return None
    names = unique(hit.names or [])
    all_records = unique(name_record(record) for record in hit.name_records or [])
    records = all_records[:_NAMES_LISTED]
    in_records = {spelling for record in all_records for spelling in (record.name, record.original)}
    other_names = [name for name in names if name not in in_records]
    addresses = hit.addresses or []
    return EntityMatch(
        pid=hit.pid,
        entity_type=hit.entity_type,
        name=display_name(all_records, names),
        name_count=len(unique([*names, *in_records])),
        name_records=records,
        other_names=other_names[: _NAMES_LISTED - len(records)],
        dates=dates_by_kind(hit.dates),
        countries=unique(hit.countries or []),
        addresses=addresses[:_ADDRESSES_LISTED],
        sanctioned=bool(hit.sanction),
        politically_exposed=bool(hit.pep),
        sanction_statuses=hit.sanction_statuses or {},
        alerts=visible_alert_texts(hit.alerts),
        identifiers=hit.unis or {},
    )


class EntitySearchQuery(PageQuery):
    name: str = Field(min_length=1)
    entity_type: EntityType | None = None
    countries: list[str] = []
    dates: list[PartialDate] = []
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=10)


class EntityMatch(BaseModel):
    """An organization or person the search matched."""

    pid: str = Field(
        description="Polixis' permanent id, which every other Polixis tool takes as `pid`."
    )
    entity_type: str | None = Field(
        description="PERSON or ORGANIZATION; vessels and aircraft are organizations."
    )
    name: str | None = Field(
        description="Computed by this MCP from Polixis's names and name records: its "
        "CURRENT_NAME record, else the first name Polixis lists, else its first name record."
    )
    name_count: int = Field(
        description="Computed by this MCP: how many distinct names and spellings Polixis holds "
        "for it, of which `name_records` and `other_names` list ten at most."
    )
    name_records: list[NameRecordView] = Field(
        description="Its first ten typed names, with the original script."
    )
    other_names: list[str] = Field(
        description="Spellings in Polixis's `names` that no name record holds, as many as fit "
        "in the ten names listed."
    )
    dates: dict[str, list[str]] = Field(
        description=(
            "Dates by kind, such as Date of Birth or Registration Date, as YYYY-MM-DD, YYYY-MM "
            "or YYYY when that is all Polixis knows."
        )
    )
    countries: list[str] = Field(description="ISO 3166-1 alpha-2 codes of its countries.")
    addresses: list[str] = Field(description="Its first three addresses.")
    sanctioned: bool = Field(
        description="Polixis's `sanction`: whether it is designated on a sanctions list Polixis "
        "covers, such as the UN, EU, OFAC, UK, Swiss, Canadian, French or Australian lists. A "
        "sanction of another authority shows in `alerts` instead."
    )
    politically_exposed: bool = Field(
        description="Polixis's `pep`: whether it is flagged as a politically exposed person. "
        "Polixis declassifies a PEP 5 years after the function ended and flags them FORMER_PEP, "
        "which this may not show: the `flags` of `get_entity_profiles` do."
    )
    sanction_statuses: dict[str, str] = Field(
        description="Sanctions list name to its status, ACTIVE or DELISTED."
    )
    alerts: list[str] = Field(description=ALERT_TEXTS_DESCRIPTION)
    identifiers: dict[str, list[str]] = Field(
        description="Identifiers by type, such as registration numbers, LEIs, tax ids or, for a "
        "vessel, IMO numbers."
    )


class EntitySearchResults(BaseModel):
    """One page of matches, best first: Polixis puts exact matches first, then those one and
    then two edits away, and ranks each group by its own logic, which favours entities with
    risks and prominent ones.
    """

    results: list[EntityMatch] = Field(description="The matches on this page.")
    total_matches: int | None = Field(
        description="Matches across every page, or null when Polixis does not say."
    )
    next_cursor: str | None = Field(
        description="Pass it as `cursor` for the next page; null on the last page."
    )
    freshness: Freshness
