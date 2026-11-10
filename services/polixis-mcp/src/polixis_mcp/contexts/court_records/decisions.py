from typing import Literal

from pydantic import BaseModel

from polixis_mcp.contexts.cached_calls import cached_call
from polixis_mcp.persistence import Persistence
from polixis_mcp.upstream import GET_JUDICIAL_RECORDS
from polixis_mcp.upstream import GetJudicialRecordsPath
from polixis_mcp.upstream import GetJudicialRecordsRequest
from polixis_mcp.upstream import JudicialRecord
from polixis_mcp.upstream import Upstream

DecisionSubject = Literal["entity", "related_party"]


async def fetch_decisions(
    *, upstream: Upstream, persistence: Persistence, pid: str
) -> list[Decision]:
    """Every decision Polixis holds for the entity and its related parties. Polixis answers
    `{}` for an id it does not know, so an unknown id reads as one without decisions.
    """
    records = await cached_call(
        upstream=upstream,
        persistence=persistence,
        operation=GET_JUDICIAL_RECORDS,
        request=GetJudicialRecordsRequest(path=GetJudicialRecordsPath(id=pid)),
    )
    subjects: list[tuple[DecisionSubject, dict[str, list[JudicialRecord]] | None]] = [
        ("entity", records.root_judicial_details),
        ("related_party", records.related_judicial_details),
    ]
    return [
        Decision(subject=subject, record=record)
        for subject, by_country in subjects
        for country_records in (by_country or {}).values()
        for record in country_records
        if record.id
    ]


def without_highlights(snippet: str) -> str:
    """The snippet without the `<em>` tags Polixis puts around the matched name."""
    return snippet.replace("<em>", "").replace("</em>", "")


class Decision(BaseModel):
    subject: DecisionSubject
    record: JudicialRecord
