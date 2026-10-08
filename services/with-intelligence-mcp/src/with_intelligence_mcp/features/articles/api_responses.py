"""With Intelligence's article shapes, from the v3 schemas.

An article is editorial coverage tagged to a firm. The listing carries the title and date; the
excerpt, body, author, and tagged firms live on the detail record.
"""

from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict

from with_intelligence_mcp.features.investors import ClassificationAttributes
from with_intelligence_mcp.with_intelligence_client import SEQUENCE, SINGLE


class ArticleFirmAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    entity_id: int | None = None
    is_primary: bool | None = None
    type: str | None = None


class ArticleAuthorAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int | None = None
    display_name: str | None = None


class ArticleDocumentAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    title: str | None = None
    url: str | None = None


class ArticleListItemAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int
    post_title: str | None = None
    post_date: str | None = None


class ArticleExtendedAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int
    post_title: str | None = None
    post_date: str | None = None
    post_excerpt: str | None = None
    post_content: str | None = None
    post_name: str | None = None
    article_type: Annotated[ClassificationAttributes | None, SINGLE] = None
    post_author: Annotated[ArticleAuthorAttributes | None, SINGLE] = None
    document: Annotated[ArticleDocumentAttributes | None, SINGLE] = None
    post_firms: Annotated[list[ArticleFirmAttributes] | None, SEQUENCE] = None
