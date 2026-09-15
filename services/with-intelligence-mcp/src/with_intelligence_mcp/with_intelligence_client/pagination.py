"""WI API pagination."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class PageInfo(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    page: int = 1
    page_size: int = 0
    count: int = 0
    total: int = 0


class Page[T](BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    pagination: PageInfo = Field(default_factory=PageInfo)
    results: list[T] = Field(default_factory=list)

    @property
    def has_more(self) -> bool:
        seen = (self.pagination.page - 1) * self.pagination.page_size + len(self.results)
        return seen < self.pagination.total
