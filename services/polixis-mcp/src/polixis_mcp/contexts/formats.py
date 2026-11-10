from collections.abc import Iterable
from datetime import datetime
from datetime import UTC
from typing import Annotated

from pydantic import Field

from polixis_mcp.upstream import DateEntry
from polixis_mcp.upstream import NodeMeta

# A date as precise as it is known, `YYYY`, `YYYY-MM` or `YYYY-MM-DD`: the one form every tool
# takes and returns a date in, whichever of its three forms Polixis uses.
PartialDate = Annotated[str, Field(pattern=r"^\d{4}(-\d{2}(-\d{2})?)?$")]


def polixis_date_number(date: str) -> int:
    """`1978-02` as 19780200: the search takes yyyyMMdd with 00 for an unknown month or day."""
    year, month, day = (date.split("-") + ["00", "00"])[:3]
    return int(f"{year}{month}{day}")


def record_date(text: str) -> str:
    """A date as a sanctions record writes it, as `YYYY-MM-DD`. The lists Polixis relays write
    2022-02-24, 13/06/2024, 14-Apr-2022 or 25/Mar/2022, the day before the month in each. Text
    in none of those forms comes back as it is.
    """
    for form in _RECORD_DATE_FORMS:
        try:
            return datetime.strptime(text.strip(), form).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    return text


def partial_date(part: DateEntry | None) -> str | None:
    """`YYYY-MM-DD`, `YYYY-MM` or `YYYY`, as much as Polixis knows, or None without a year."""
    if part is None or not part.y:
        return None
    if not part.m:
        return f"{part.y:04d}"
    if not part.d:
        return f"{part.y:04d}-{part.m:02d}"
    return f"{part.y:04d}-{part.m:02d}-{part.d:02d}"


def unix_date(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    return datetime.fromtimestamp(seconds, UTC).date().isoformat()


def dates_by_kind(dates: dict[str, list[DateEntry]] | None) -> dict[str, list[str]]:
    return {
        kind: formatted
        for kind, parts in (dates or {}).items()
        if (formatted := unique(partial_date(part) for part in parts))
    }


def node_name(meta: NodeMeta | None) -> str | None:
    """The first English name of a graph or tree node, else its first original one."""
    names = (meta.names if meta is not None else None) or {}
    return next(iter(names.get("en") or names.get("original") or []), None)


def unique[T](values: Iterable[T | None]) -> list[T]:
    """The values in their first order, without repeats or None."""
    return list(dict.fromkeys(value for value in values if value is not None))


_RECORD_DATE_FORMS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y", "%d/%b/%Y")
