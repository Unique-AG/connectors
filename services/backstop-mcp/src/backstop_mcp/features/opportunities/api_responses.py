from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from backstop_mcp.lenient import LenientBool, LenientInt

__all__ = ["OpportunityStageAttributes", "SearchContactAttributes", "SearchProductAttributes"]

_StrippedStr = Annotated[str, StringConstraints(strip_whitespace=True)]


class OpportunityStageAttributes(BaseModel):
    """Wire shape for `opportunity-stages` attributes (the vocabulary subset).

    Every field is optional because `client.paginate` deserializes a whole page in one pass: a
    required field would fail the entire seven-row fetch over one malformed row. Optional fields
    plus the drop in `OpportunityStageDto.from_resource` keep one bad row from costing the other
    six.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: _StrippedStr | None = None
    sort_order: LenientInt = Field(default=None, alias="sortOrder")
    closed: LenientBool = None


class SearchContactAttributes(BaseModel):
    """Sparse `contacts` attributes from the investor include on `GET /opportunities`."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: str | None = None
    country: str | None = None
    state: str | None = None
    city: str | None = None


class SearchProductAttributes(BaseModel):
    """Sparse `products` attributes from the product include on `GET /opportunities`."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: str | None = None
