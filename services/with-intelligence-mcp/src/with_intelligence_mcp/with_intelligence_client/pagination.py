"""The one paging shape every v3 listing returns.

    {"pagination": {"page": 1, "page_size": 50, "count": 50, "total": 4321}, "results": [...]}

`count` is this page, `total` the whole match. One helper serves all 143 paths.
"""

from typing import ClassVar, cast

from pydantic import BaseModel, ConfigDict, Field


class PageInfo(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    page: int = 1
    page_size: int = 0
    count: int = 0
    total: int = 0


class Page(BaseModel):
    """A listing response, results left unparsed for the feature to model."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    pagination: PageInfo = Field(default_factory=PageInfo)
    results: list[dict[str, object]] = Field(default_factory=list)

    @property
    def has_more(self) -> bool:
        seen = (self.pagination.page - 1) * self.pagination.page_size + len(self.results)
        return seen < self.pagination.total


def parse_page(body: object) -> Page:
    if not isinstance(body, dict):
        return Page()
    return Page.model_validate(cast(dict[str, object], body))
