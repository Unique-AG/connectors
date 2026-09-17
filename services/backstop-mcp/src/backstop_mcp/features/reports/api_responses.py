"""Wire shape for `GET /reports`.

Each HTTP page is one `reports` resource. The rows live in `attributes.result.values`;
`page[limit]` / `page[offset]` / `meta.totalResourceCount` count those rows, not `data[]`.
"""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.backstop_client import BackstopApiResource
from backstop_mcp.lenient import LenientStr

__all__ = [
    "ReportHeaderAttributes",
    "ReportResource",
    "ReportResourceAttributes",
    "ReportResultAttributes",
]


class ReportHeaderAttributes(BaseModel):
    """One column descriptor on `result.header`."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    title: LenientStr = None
    name: LenientStr = None


class ReportResultAttributes(BaseModel):
    """The table inside `attributes.result`."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    header: list[ReportHeaderAttributes] = Field(default_factory=list)
    values: list[object] = Field(default_factory=list)


class ReportResourceAttributes(BaseModel):
    """Attributes on one `reports` resource. Every field optional: one bad page must not 500."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    result: ReportResultAttributes | None = None


ReportResource = BackstopApiResource[ReportResourceAttributes]
