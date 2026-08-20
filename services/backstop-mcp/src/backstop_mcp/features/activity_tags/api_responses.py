from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from backstop_mcp.lenient import LenientBool, LenientInt

__all__ = ["ActivityTagAttributes"]

_StrippedStr = Annotated[str, StringConstraints(strip_whitespace=True)]


class ActivityTagAttributes(BaseModel):
    """Wire shape for `activity-tags` attributes (subset we need).

    Every field is optional because `client.paginate` deserializes a whole page in one pass: a
    required field would fail the entire catalog fetch over one malformed row. Optional fields
    plus the drop in `ActivityTagDto.from_resource` keep one bad row from costing the rest.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: _StrippedStr | None = None
    quantity_tagged: LenientInt = Field(default=None, alias="quantityTagged")
    viewable: LenientBool = None
