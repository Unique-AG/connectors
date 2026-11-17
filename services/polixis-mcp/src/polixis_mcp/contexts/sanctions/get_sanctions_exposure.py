from pydantic import BaseModel
from pydantic import Field

from polixis_mcp.contexts.cached_calls import cached_call
from polixis_mcp.contexts.formats import record_date
from polixis_mcp.contexts.formats import unique
from polixis_mcp.contexts.formats import unix_date
from polixis_mcp.contexts.pages import encode_cursor
from polixis_mcp.contexts.pages import page_of
from polixis_mcp.contexts.pages import PageQuery
from polixis_mcp.contexts.pages import QueryPid
from polixis_mcp.contexts.pages import snapshot_for
from polixis_mcp.persistence import Persistence
from polixis_mcp.upstream import GET_SANCTION_EXPOSURE
from polixis_mcp.upstream import GetSanctionExposurePath
from polixis_mcp.upstream import GetSanctionExposureRequest
from polixis_mcp.upstream import SanctionedParty
from polixis_mcp.upstream import SanctionPathHop
from polixis_mcp.upstream import SanctionRecord
from polixis_mcp.upstream import Upstream

# The lists name the date of a listing differently; the first a record has is its listing date.
_LISTING_DATE_KEYS = ("Listing Date", "Listed Date", "#UK_DESIGNATED_DATE")


async def get_sanctions_exposure(
    *, upstream: Upstream, persistence: Persistence, query: SanctionsExposureQuery
) -> SanctionsExposurePage:
    """Polixis walks its graph itself, with no hop limit we can set, and returns the whole
    result at once, so the next page reads it from the cache. The nearest come first, the ones
    with an active listing before the others at the same distance.
    """
    exposure = await cached_call(
        upstream=upstream,
        persistence=persistence,
        operation=GET_SANCTION_EXPOSURE,
        request=GetSanctionExposureRequest(path=GetSanctionExposurePath(id=query.pid)),
    )
    related = sorted(
        (_related(party) for party in exposure.related_sanctions or []),
        key=lambda party: (
            party.hops is None,
            party.hops or 0,
            not any(listing.status == "ACTIVE" for listing in party.listings),
            party.name is None,
            party.name or "",
            party.pid or "",
        ),
    )
    snapshot = snapshot_for(query, related)
    page, next_offset = page_of(related, offset=query.offset, size=query.page_size)
    return SanctionsExposurePage(
        pid=query.pid,
        own_listings=[
            _listing(_detail(record, "Source") or "unnamed list", record)
            for record in exposure.direct_sanctions or []
        ],
        total_related=len(related),
        related=page,
        next_cursor=(
            encode_cursor(query.model_copy(update={"offset": next_offset, "snapshot": snapshot}))
            if next_offset is not None
            else None
        ),
    )


def _related(party: SanctionedParty) -> SanctionedRelatedParty:
    hops = party.relation_paths or []
    return SanctionedRelatedParty(
        pid=party.pid or None,
        name=party.name_en,
        countries=unique(code for codes in (party.countries or {}).values() for code in codes),
        listings=[
            _listing(list_name, record)
            for list_name, records in (party.sanctions or {}).items()
            for record in records
        ],
        hops=_distance(hops),
        path=[link for hop in hops if (link := _path_link(hop)) is not None],
    )


def _distance(hops: list[SanctionPathHop]) -> int | None:
    """The distinct pairs of named ends; None when a hop lacks a name, since Polixis gives the
    ends no pid and unnamed ones cannot be told apart.
    """
    if not hops or not all(hop.source_name and hop.target_name for hop in hops):
        return None
    return len(unique((hop.source_name, hop.target_name) for hop in hops))


def _listing(list_name: str, record: SanctionRecord) -> Listing:
    return Listing(
        list_name=list_name,
        country=record.country,
        status=_detail(record, "Sanction Status"),
        programs=(record.details or {}).get("Program", []),
        listed_on=next(
            (record_date(date) for key in _LISTING_DATE_KEYS if (date := _detail(record, key))),
            None,
        ),
    )


def _detail(record: SanctionRecord, key: str) -> str | None:
    return next(iter((record.details or {}).get(key, [])), None)


def _path_link(hop: SanctionPathHop) -> SanctionPathLink | None:
    connection = hop.connection
    if connection is None:
        return None
    return SanctionPathLink(
        source_name=hop.source_name,
        target_name=hop.target_name,
        role=connection.role,
        share_percent=connection.share or None,
        former=bool(connection.former),
        start_date=unix_date(connection.start_date),
        end_date=unix_date(connection.end_date),
    )


class SanctionsExposureQuery(PageQuery):
    pid: QueryPid
    page_size: int | None = Field(default=None, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class Listing(BaseModel):
    """One record on one sanctions list. Polixis counts each authority's list once, such as
    one OFAC list for every OFAC programme.
    """

    list_name: str = Field(description="The sanctions list.")
    country: str | None = Field(description="ISO 3166-1 alpha-2 code of the listing authority.")
    status: str | None = Field(
        description="The record's Sanction Status detail, ACTIVE or DELISTED, as it gives it."
    )
    programs: list[str] = Field(
        description="The record's Program details, such as UKRAINE-EO13662."
    )
    listed_on: str | None = Field(
        description="Computed by this MCP from the record's Listing Date, Listed Date or "
        "#UK_DESIGNATED_DATE detail, whichever it has first, as YYYY-MM-DD, or as the record "
        "writes it when in no form we know; null when the record gives none."
    )


class SanctionPathLink(BaseModel):
    """One relation on the way to a sanctioned party: the source holds the role in the target.
    Polixis names the two ends but gives no pid.
    """

    source_name: str | None = Field(description="The party holding the role.")
    target_name: str | None = Field(description="The party the role is held in.")
    role: str | None = Field(description="Such as shareholder, director or nephew.")
    share_percent: float | None = Field(description="The share held; null when not reported.")
    former: bool = Field(description="Whether the relation has ended.")
    start_date: str | None = Field(description="YYYY-MM-DD, null if unknown.")
    end_date: str | None = Field(description="YYYY-MM-DD, null if unknown or current.")


class SanctionedRelatedParty(BaseModel):
    """A sanctioned party related to the entity, and the relations that lead to it."""

    pid: str | None = Field(
        description="Its pid, for the other Polixis tools; null when Polixis gives none."
    )
    name: str | None = Field(description="Its English name.")
    countries: list[str] = Field(description="ISO 3166-1 alpha-2 codes it is tied to.")
    listings: list[Listing] = Field(description="Its records on sanctions lists.")
    hops: int | None = Field(
        description="Computed by this MCP: the distinct pairs of parties on its path, so the "
        "links between the entity and it; 1 is a direct relation. Null when Polixis leaves a "
        "party on the path unnamed, so the distance is unknown."
    )
    path: list[SanctionPathLink] = Field(
        description="Polixis's relations from the entity to it, in order. Two parties joined "
        "by several relations have one entry for each."
    )


class SanctionsExposurePage(BaseModel):
    """An entity's own sanctions listings and the sanctioned parties related to it, one page of
    the latter.
    """

    pid: str = Field(description="The entity asked about.")
    own_listings: list[Listing] = Field(
        description="The entity's own records on sanctions lists, each named by its Source "
        "detail; empty when it is not listed."
    )
    total_related: int = Field(
        description="Computed by this MCP: sanctioned related parties across every page. "
        "Polixis has returned "
        "different counts for the same entity on two calls, so say when a count matters."
    )
    related: list[SanctionedRelatedParty] = Field(
        description="The sanctioned related parties of this page, the nearest first."
    )
    next_cursor: str | None = Field(
        description="Pass it as `cursor` for the next page; null on the last page."
    )
