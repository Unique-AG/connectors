from pydantic import BaseModel
from pydantic import Field

from polixis_mcp.contexts.court_records.decisions import DecisionSubject
from polixis_mcp.contexts.court_records.decisions import fetch_decisions
from polixis_mcp.contexts.pages import encode_cursor
from polixis_mcp.contexts.pages import PageQuery
from polixis_mcp.contexts.pages import QueryPid
from polixis_mcp.contexts.pages import snapshot_for
from polixis_mcp.contexts.pages import text_page
from polixis_mcp.persistence import Persistence
from polixis_mcp.upstream import Upstream


async def get_court_decision(
    *, upstream: Upstream, persistence: Persistence, query: CourtDecisionTextQuery
) -> CourtDecisionText:
    """Polixis has no route for one decision, so this reads them all, usually from the cache
    `find_court_decisions` filled, and keeps the one.
    """
    decision = next(
        (
            decision
            for decision in await fetch_decisions(
                upstream=upstream, persistence=persistence, pid=query.pid
            )
            if decision.record.id == query.decision_id
        ),
        None,
    )
    if decision is None:
        raise CourtDecisionNotFoundError(
            f"Polixis has no decision {query.decision_id} for {query.pid}. Take the id from "
            "`find_court_decisions` on the same pid."
        )
    text = decision.record.content or ""
    snapshot = snapshot_for(query, [text])
    part, next_offset = text_page(text, offset=query.offset)
    return CourtDecisionText(
        pid=query.pid,
        decision_id=query.decision_id,
        subject=decision.subject,
        court_type=decision.record.court_type,
        country=(decision.record.country or "").upper() or None,
        year=decision.record.year,
        total_characters=len(text),
        text=part,
        next_cursor=(
            encode_cursor(query.model_copy(update={"offset": next_offset, "snapshot": snapshot}))
            if next_offset is not None
            else None
        ),
    )


class CourtDecisionTextQuery(PageQuery):
    pid: QueryPid
    decision_id: str = Field(min_length=1)
    offset: int = Field(default=0, ge=0)


class CourtDecisionText(BaseModel):
    """The text of one court decision, one part of it."""

    pid: str = Field(description="The entity the decision was found for.")
    decision_id: str = Field(description="The decision's id.")
    subject: DecisionSubject = Field(
        description="`entity` when it names the entity, `related_party` when a related party."
    )
    court_type: str | None = Field(description="Such as General Instance Court.")
    country: str | None = Field(description="ISO 3166-1 alpha-2 code of the court's country.")
    year: str | None = Field(description="The year of the decision.")
    total_characters: int = Field(description="The length of the whole text, in characters.")
    text: str = Field(description="This part of the text, in the decision's own language.")
    next_cursor: str | None = Field(
        description="Pass it as `cursor` for the next part; null on the last."
    )


class CourtDecisionNotFoundError(Exception):
    """The entity has no decision with that id."""
