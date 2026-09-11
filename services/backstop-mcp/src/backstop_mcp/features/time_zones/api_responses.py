from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.models import StrippedStr

__all__ = ["TimeZoneAttributes"]


class TimeZoneAttributes(BaseModel):
    """Wire shape for `time-zones` attributes (subset we need).

    Every field is optional because `client.paginate` deserializes a whole page in one pass: a
    required field would fail the entire catalog fetch over one malformed row. Optional fields
    plus the drop in `TimeZoneDto.from_resource` keep one bad row from costing the rest.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: StrippedStr | None = None
    short_name: StrippedStr | None = Field(default=None, validation_alias="shortName")
