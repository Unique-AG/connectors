from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.lenient import LenientBool, LenientInt
from backstop_mcp.models import StrippedStr

__all__ = ["ActivityTagAttributes"]


class ActivityTagAttributes(BaseModel):
    """Wire shape for `activity-tags` attributes (subset we need).

    Every field is optional because `client.paginate` deserializes a whole page in one pass: a
    required field would fail the entire catalog fetch over one malformed row. Optional fields
    plus the drop in `ActivityTagDto.from_resource` keep one bad row from costing the rest.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: StrippedStr | None = None
    quantity_tagged: LenientInt = Field(default=None, alias="quantityTagged")
    viewable: LenientBool = None
