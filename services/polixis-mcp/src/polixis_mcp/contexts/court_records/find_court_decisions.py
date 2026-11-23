from pydantic import BaseModel
from pydantic import Field

from polixis_mcp.contexts.court_records.decisions import DecisionSubject
from polixis_mcp.contexts.court_records.decisions import fetch_decisions
from polixis_mcp.contexts.court_records.decisions import without_highlights
from polixis_mcp.contexts.freshness import Freshness
from polixis_mcp.contexts.freshness import freshness
from polixis_mcp.contexts.pages import encode_cursor
from polixis_mcp.contexts.pages import page_of
from polixis_mcp.contexts.pages import PageQuery
from polixis_mcp.contexts.pages import QueryPid
from polixis_mcp.contexts.pages import snapshot_for
from polixis_mcp.upstream import Upstream


async def find_court_decisions(
    *, upstream: Upstream, query: CourtDecisionsQuery
) -> CourtDecisionsPage:
    """The decisions naming the entity itself first, then the most recent."""
    decisions = [
        CourtDecisionSummary(
            decision_id=decision.record.id or "",
            subject=decision.subject,
            court_type=decision.record.court_type,
            country=(decision.record.country or "").upper() or None,
            year=decision.record.year,
            snippets=[without_highlights(snippet) for snippet in decision.record.snippet or []],
            text_characters=len(decision.record.content or ""),
        )
        for decision in sorted(
            await fetch_decisions(upstream=upstream, pid=query.pid),
            key=lambda decision: (decision.subject != "entity", -_year(decision.record.year)),
        )
    ]
    snapshot = snapshot_for(query, decisions)
    page, next_offset = page_of(decisions, offset=query.offset, size=query.page_size)
    return CourtDecisionsPage(
        pid=query.pid,
        total_decisions=len(decisions),
        total_naming_entity=sum(1 for decision in decisions if decision.subject == "entity"),
        decisions=page,
        next_cursor=(
            encode_cursor(query.model_copy(update={"offset": next_offset, "snapshot": snapshot}))
            if next_offset is not None
            else None
        ),
        freshness=freshness(),
    )


def _year(year: str | None) -> int:
    return int(year) if year and year.isdecimal() else 0


class CourtDecisionsQuery(PageQuery):
    pid: QueryPid
    page_size: int | None = Field(default=None, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class CourtDecisionSummary(BaseModel):
    """A court decision, without its text."""

    decision_id: str = Field(description="Its id, for `get_court_decision`.")
    subject: DecisionSubject = Field(
        description="Which of Polixis's two lists it came from: `entity` when it names the "
        "entity asked about, `related_party` when it names one of its related parties, which "
        "Polixis does not say."
    )
    court_type: str | None = Field(description="Such as General Instance Court.")
    country: str | None = Field(description="ISO 3166-1 alpha-2 code of the court's country.")
    year: str | None = Field(description="The year of the decision.")
    snippets: list[str] = Field(
        description="Polixis's passages where the name appears, in the decision's own "
        "language, without its highlight tags."
    )
    text_characters: int = Field(
        description="Computed by this MCP: the length of its full text, in characters."
    )


class CourtDecisionsPage(BaseModel):
    """Court decisions naming an entity or its related parties, one page of them."""

    pid: str = Field(description="The entity asked about.")
    total_decisions: int = Field(
        description="Decisions across every page. Polixis answers an id it does not know as "
        "one without decisions, so 0 also follows a wrong pid."
    )
    total_naming_entity: int = Field(description="Decisions naming the entity itself.")
    decisions: list[CourtDecisionSummary] = Field(
        description="The decisions of this page: those naming the entity first, then the newest."
    )
    next_cursor: str | None = Field(
        description="Pass it as `cursor` for the next page; null on the last page."
    )
    freshness: Freshness
