from typing import Literal

from pydantic import BaseModel
from pydantic import Field

from polixis_mcp.contexts.formats import partial_date
from polixis_mcp.contexts.formats import unique
from polixis_mcp.contexts.pages import encode_cursor
from polixis_mcp.contexts.pages import PageQuery
from polixis_mcp.contexts.risks import ALERT_TEXTS_DESCRIPTION
from polixis_mcp.contexts.risks import FLAGS_DESCRIPTION
from polixis_mcp.contexts.risks import visible_alert_texts
from polixis_mcp.upstream import CorporateNodeData
from polixis_mcp.upstream import CorporateRequestInput
from polixis_mcp.upstream import GET_CORPORATE_PROFILE
from polixis_mcp.upstream import GetCorporateProfileQuery
from polixis_mcp.upstream import GetCorporateProfileRequest
from polixis_mcp.upstream import Upstream

RelationCategory = Literal[
    "executive",
    "executiveSenior",
    "board",
    "political",
    "signature",
    "thirdParty",
    "membership",
    "shareholdingInformation",
    "ownershipInOtherEntities",
]


async def get_related_parties(
    *, upstream: Upstream, query: RelatedPartiesQuery
) -> RelatedPartiesPage:
    response = await upstream.call(
        GET_CORPORATE_PROFILE,
        GetCorporateProfileRequest(
            query=GetCorporateProfileQuery(page=query.page, size=query.page_size),
            body=CorporateRequestInput(id=query.pid, category=list(query.categories)),
        ),
    )
    return RelatedPartiesPage(
        pid=query.pid,
        total_parties=response.total_elements,
        parties=[party for item in response.data or [] if (party := _party(item)) is not None],
        next_cursor=(
            encode_cursor(query.model_copy(update={"page": query.page + 1}))
            if response.has_next
            else None
        ),
    )


def _party(item: CorporateNodeData) -> RelatedPartyView | None:
    """None for a party with neither a pid nor a name, which says nothing about who it is."""
    entity = item.entity
    if entity is None:
        return None
    first_name = next(iter(entity.names or []), None)
    name = (first_name.en or first_name.original) if first_name is not None else None
    if not entity.pid and not name:
        return None
    return RelatedPartyView(
        pid=entity.pid or None,
        name=name,
        entity_type=entity.type,
        countries=unique(code for codes in (entity.countries or {}).values() for code in codes),
        flags=unique(name for flag in entity.flags or [] for name in flag),
        alerts=visible_alert_texts(entity.alerts),
        relations=[
            RelationView(
                relation_type=relation.type,
                title=detail.title,
                share_percent=_share(detail.properties),
                former=bool(detail.former),
                start_date=partial_date((detail.dates or {}).get("Start Date")),
                end_date=partial_date((detail.dates or {}).get("End Date")),
                information_date=partial_date((detail.dates or {}).get("Date of Information")),
                source=detail.metadata.source_name if detail.metadata is not None else None,
            )
            for relation in item.relation or []
            for detail in relation.relation_property or []
        ],
    )


def _share(properties: dict[str, list[str]] | None) -> float | None:
    """The `Share` property as a number; Polixis sends it as text, 0 when not reported."""
    text = next(iter((properties or {}).get("Share", [])), None)
    try:
        share = float(text) if text is not None else None
    except ValueError:
        return None
    return share or None


_ALL_CATEGORIES: tuple[RelationCategory, ...] = (
    "executive",
    "executiveSenior",
    "board",
    "political",
    "signature",
    "thirdParty",
    "membership",
    "shareholdingInformation",
    "ownershipInOtherEntities",
)


class RelatedPartiesQuery(PageQuery):
    pid: str = Field(min_length=1)
    categories: tuple[RelationCategory, ...] = Field(default=_ALL_CATEGORIES, min_length=1)
    page: int = Field(default=0, ge=0)
    page_size: int = Field(default=40, ge=1, le=45)


class RelationView(BaseModel):
    """One relation of the party to the entity, as one source reports it."""

    relation_type: str | None = Field(
        description=(
            "Polixis' kind of relation, such as executive, shareholding_ownership (the party "
            "holds shares in the entity) or shareholding_ownership_reverse (the entity holds "
            "shares in the party)."
        )
    )
    title: str | None = Field(
        description="The party's role, such as director, investor or ultimately consolidated by."
    )
    share_percent: float | None = Field(
        description="The relation's Share property, which Polixis sends as text, as a number; "
        "null when it is missing or 0, which Polixis sends for a share it does not know."
    )
    former: bool = Field(description="Polixis's `former`: whether the relation has ended.")
    start_date: str | None = Field(description="YYYY-MM-DD, YYYY-MM or YYYY, null if unknown.")
    end_date: str | None = Field(description="YYYY-MM-DD, YYYY-MM or YYYY, null if unknown.")
    information_date: str | None = Field(
        description="When the source reported it, YYYY-MM-DD, YYYY-MM or YYYY."
    )
    source: str | None = Field(description="The register or list that reports the relation.")


class RelatedPartyView(BaseModel):
    """An organization or person related to the entity, with how."""

    pid: str | None = Field(
        description="The party's pid, for the other Polixis tools; null when Polixis gives "
        "none, so no other tool can look the party up."
    )
    name: str | None = Field(description="Its name, in English where Polixis has one.")
    entity_type: str | None = Field(
        description="PERSON or ORGANIZATION; vessels and aircraft are organizations."
    )
    countries: list[str] = Field(description="ISO 3166-1 alpha-2 codes of its countries.")
    flags: list[str] = Field(description=FLAGS_DESCRIPTION)
    alerts: list[str] = Field(description=ALERT_TEXTS_DESCRIPTION)
    relations: list[RelationView] = Field(
        description="Every relation to the entity, one per source that reports it."
    )


class RelatedPartiesPage(BaseModel):
    """One page of the parties related to an entity."""

    pid: str = Field(description="The entity asked about.")
    total_parties: int | None = Field(
        description="Related parties across every page, or null when Polixis does not say. "
        "It counts the parties with neither a pid nor a name, which the pages leave out."
    )
    parties: list[RelatedPartyView] = Field(description="The parties of this page.")
    next_cursor: str | None = Field(
        description="Pass it as `cursor` for the next page; null on the last page."
    )
