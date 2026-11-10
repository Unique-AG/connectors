from pydantic import BaseModel
from pydantic import Field

from polixis_mcp.upstream import NameRecord


def name_record(record: NameRecord) -> NameRecordView | None:
    """None for a record without a name. `original` only when it differs from the Latin name,
    which it repeats for most records.
    """
    name = record.en or record.original
    if not name:
        return None
    return NameRecordView(
        name=name,
        original=record.original if record.original != name else None,
        language=record.language,
        kind=record.type,
    )


class NameRecordView(BaseModel, frozen=True):
    """A name the entity is known by, with its kind and original script."""

    name: str = Field(description="The name in Latin script.")
    original: str | None = Field(
        description="The name as written in its own script; null when it is `name` itself."
    )
    language: str | None = Field(description="ISO 639-1 code of the original name.")
    kind: str | None = Field(description="Such as CURRENT_NAME, FORMER_NAME, TRADE_NAME or ALIAS.")
