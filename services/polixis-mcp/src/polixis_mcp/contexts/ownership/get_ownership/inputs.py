from typing import Literal

from pydantic import Field

from polixis_mcp.contexts.pages import PageQuery
from polixis_mcp.contexts.pages import QueryPid

OwnershipDirection = Literal["owners", "holdings"]


class OwnershipQuery(PageQuery):
    pid: QueryPid
    direction: OwnershipDirection
    page_size: int | None = Field(default=None, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
