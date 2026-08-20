"""One winner per `(person_id, organization_id)` pair, folded from employment edges.

Tools do not call this directly — they go through `EmploymentIndexFactory`, which owns the
employment vocabulary and assembles the edges. List/org-contact tools should use that verdict to
exclude departed people from "who do we contact at X" answers unless the user asked for historical
contacts; a by-id person fetch returns the person with employment links rather than hiding the
record.
"""

from collections.abc import Sequence
from datetime import date

from backstop_mcp.features.data_hygiene.internal_dto import (
    DepartedEmploymentDto,
    EmploymentEdgeDto,
    EmploymentRecordDto,
    EmploymentStatus,
)
from backstop_mcp.features.data_hygiene.responses import EmploymentLinkResponse


class EmploymentIndex:
    """One winner per `(person_id, organization_id)` pair, folded out of `_employment_edges`.

    A tenant's `entityRelationships` can carry several records for the same pair — a live `is
    employee of` alongside an ended `is a former employee of`, or successive relationships across
    a re-hire — and the caller needs one verdict, not a list to re-resolve on every read. The fold
    happens once, in `__init__`; every query method after that is a plain dict lookup.

    Winner per pair: the edge with the greatest `effective_date`. A tie breaks toward **departed**
    — a same-day former record is the more recent human action, and under-reporting a departure is
    the costlier error for a "who do we contact" answer. An edge with no usable date at all still
    counts, but sorts behind every dated edge for its pair, so it only wins when it is the sole
    edge for that pair.
    """

    def __init__(self, edges: Sequence[EmploymentEdgeDto]) -> None:
        winners: dict[tuple[str, str], EmploymentEdgeDto] = {}
        for edge in edges:
            key = (edge.person_id, edge.organization_id)
            current = winners.get(key)
            if current is None or _outranks(edge, current):
                winners[key] = edge
        self._records: dict[tuple[str, str], EmploymentRecordDto] = {
            key: _to_record(edge) for key, edge in winners.items()
        }

    def get(self, *, person_id: str, organization_id: str) -> EmploymentRecordDto | None:
        """The winning record for this pair, or `None` when the index has no employment evidence."""
        return self._records.get((person_id, organization_id))

    def status(self, *, person_id: str, organization_id: str) -> EmploymentStatus | None:
        """The winning edge's status, or `None` — "no employment evidence" — for an unknown pair.

        Never a false `CURRENT`: a pair this index has never seen is not a live employee.
        """
        record = self.get(person_id=person_id, organization_id=organization_id)
        return None if record is None else record.status

    def departure(self, *, person_id: str, organization_id: str) -> DepartedEmploymentDto | None:
        """The winning edge's departure evidence, when the pair's resolved status is `FORMER`."""
        record = self.get(person_id=person_id, organization_id=organization_id)
        if record is None or record.status is not EmploymentStatus.FORMER:
            return None
        return record.departure

    def current(self) -> tuple[EmploymentRecordDto, ...]:
        """Every resolved pair whose winning status is `CURRENT`."""
        return self.pairs(status=EmploymentStatus.CURRENT)

    def former(self) -> tuple[EmploymentRecordDto, ...]:
        """Every resolved pair whose winning status is `FORMER`."""
        return self.pairs(status=EmploymentStatus.FORMER)

    def pairs(self, *, status: EmploymentStatus) -> tuple[EmploymentRecordDto, ...]:
        """Every resolved pair whose winning status matches `status`, for list annotation."""
        return tuple(record for record in self._records.values() if record.status is status)

    def links(self) -> list[EmploymentLinkResponse]:
        """Current then former employment links — the shape tools should relay."""
        return [_to_link(record) for record in (*self.current(), *self.former())]


def _to_link(record: EmploymentRecordDto) -> EmploymentLinkResponse:
    if record.status is EmploymentStatus.CURRENT:
        status = "current"
    elif record.status is EmploymentStatus.FORMER:
        status = "former"
    else:
        raise AssertionError(
            f"EmploymentIndex only stores CURRENT/FORMER winners, got {record.status!r}"
        )
    departure = record.departure
    return EmploymentLinkResponse(
        status=status,
        person_id=record.person_id,
        person_type=record.person_type,
        organization_id=record.organization_id,
        organization_type=record.organization_type,
        signal=None if departure is None else departure.signal,
        end_date=None if departure is None else departure.end_date,
        relationship_type_id=record.relationship_type_id,
        relationship_type_name=record.relationship_type_name,
    )


def _outranks(edge: EmploymentEdgeDto, current: EmploymentEdgeDto) -> bool:
    """Whether `edge` beats `current` as the winner for their shared pair.

    Compared as `(has a date, date, is departed)` tuples so a dated edge always beats an undated
    one, the later date wins between two dated edges, and a same-day tie breaks toward `FORMER`.
    """
    return _rank(edge) > _rank(current)


def _rank(edge: EmploymentEdgeDto) -> tuple[bool, date, bool]:
    return (
        edge.effective_date is not None,
        edge.effective_date if edge.effective_date is not None else date.min,
        edge.status is EmploymentStatus.FORMER,
    )


def _to_record(edge: EmploymentEdgeDto) -> EmploymentRecordDto:
    return EmploymentRecordDto(
        person_id=edge.person_id,
        person_type=edge.person_type,
        organization_id=edge.organization_id,
        organization_type=edge.organization_type,
        status=edge.status,
        relationship_type_id=edge.relationship_type_id,
        relationship_type_name=edge.relationship_type_name,
        effective_date=edge.effective_date,
        departure=edge.departure,
    )
