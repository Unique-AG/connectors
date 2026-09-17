from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from backstop_mcp.models import StrippedStr

__all__ = ["ContactSourceAttributes"]


class ContactSourceAttributes(BaseModel):
    """Wire shape for `contact-sources` attributes (subset we publish).

    Every field is optional because `client.paginate` deserializes a whole page in one pass: a
    required field would fail the entire catalog fetch over one malformed row. Optional fields
    plus the drop in `ContactSourceDto.from_resource` keep one bad row from costing the rest.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: StrippedStr | None = None
    description: StrippedStr | None = None
