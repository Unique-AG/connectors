from typing import Literal

from pydantic import Field

from polixis_mcp.contexts.pages import PageQuery

OwnershipDirection = Literal["owners", "holdings"]


class OwnershipQuery(PageQuery):
    pid: str = Field(min_length=1)
    direction: OwnershipDirection
    page_size: int | None = Field(default=None, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
