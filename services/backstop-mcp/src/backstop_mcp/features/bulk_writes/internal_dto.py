"""What a caller of `bulk_record_outcomes` knows about one row it sent."""

from pydantic import BaseModel, Field

__all__ = ["BulkRequestedRowDto"]


class BulkRequestedRowDto(BaseModel):
    """One request row, paired with the key that identifies it in Backstop's echo.

    `match_key` is whatever the feature can compare against the landed records — a definition
    id, an `(opportunity_id, stage_id)` pair — and is only ever tested for equality.
    """

    record_id: str | None = Field(default=None)
    match_key: object = None
