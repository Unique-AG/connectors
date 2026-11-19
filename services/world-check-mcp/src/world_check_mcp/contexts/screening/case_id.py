from collections.abc import Iterable
from datetime import date
from hashlib import sha256

from world_check_mcp.contexts.screening.models import FieldValue

_SEPARATOR = "\x1f"


def derived_case_id(*parts: str | date | None) -> str:
    """The same details always give the same id, so a retried screening finds its own case."""
    material = _SEPARATOR.join(_normalized(part=part) for part in parts)
    return f"mcp-{sha256(material.encode()).hexdigest()[:32]}"


def field_parts(*, fields: Iterable[FieldValue] | None) -> list[str]:
    return sorted(
        f"{field.type_id}={_normalized(part=field.value or field.date_time_value)}"
        for field in fields or []
    )


def _normalized(*, part: str | date | None) -> str:
    return " ".join(str(part or "").casefold().split())
