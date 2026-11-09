from typing import Literal

from pydantic import BaseModel
from pydantic import Field

from polixis_mcp.upstream import SEARCH_ENTITIES
from polixis_mcp.upstream import SearchEntitiesRequest
from polixis_mcp.upstream import SearchHit
from polixis_mcp.upstream import SearchRequestInput
from polixis_mcp.upstream import Upstream

EntityType = Literal["ORGANIZATION", "PERSON"]


async def search_entities(
    *,
    upstream: Upstream,
    name: str,
    entity_type: EntityType | None,
    countries: list[str],
    page: int,
    page_size: int,
) -> EntitySearchResults:
    response = await upstream.call(
        SEARCH_ENTITIES,
        SearchEntitiesRequest(
            body=SearchRequestInput(
                name=name,
                entity_type=entity_type,
                countries=[country.lower() for country in countries],
                page=page,
                size=page_size,
            )
        ),
    )
    pagination = response.pagination
    return EntitySearchResults(
        matches=[match for hit in response.hits or [] if (match := _match(hit=hit)) is not None],
        page=page,
        total_matches=pagination.total_hits if pagination is not None else None,
    )


def _match(*, hit: SearchHit) -> EntityMatch | None:
    """None for a hit without a pid, which no other Polixis endpoint can look up."""
    if not hit.pid:
        return None
    return EntityMatch(
        pid=hit.pid,
        entity_type=hit.entity_type,
        names=hit.names or [],
        sanctioned=bool(hit.sanction),
        politically_exposed=bool(hit.pep),
        sanction_statuses=hit.sanction_statuses or {},
        alerts=[alert.description for alert in hit.alerts or [] if alert.description],
        identifiers=hit.unis or {},
    )


class EntityMatch(BaseModel):
    """An organization or person the search matched."""

    pid: str = Field(
        description="Polixis' permanent id, which every other Polixis tool takes as `id`."
    )
    entity_type: str | None = Field(
        description="PERSON or ORGANIZATION; vessels and aircraft are organizations."
    )
    names: list[str] = Field(description="Its names, aliases and original-language spellings.")
    sanctioned: bool = Field(description="Whether Polixis flags it for sanctions exposure.")
    politically_exposed: bool = Field(description="Whether Polixis flags it as a PEP.")
    sanction_statuses: dict[str, str] = Field(
        description="Sanctions list name to its status, ACTIVE or DELISTED."
    )
    alerts: list[str] = Field(description="Risk and status alerts, as Polixis words them.")
    identifiers: dict[str, list[str]] = Field(
        description="Identifiers by type, such as registration numbers, LEIs or tax ids."
    )


class EntitySearchResults(BaseModel):
    """One page of matches, best first: exact matches, then fuzzy ones."""

    matches: list[EntityMatch] = Field(description="The matches on this page.")
    page: int = Field(description="The page returned, from 1.")
    total_matches: int | None = Field(
        description="Matches across every page, or null when Polixis does not say."
    )
