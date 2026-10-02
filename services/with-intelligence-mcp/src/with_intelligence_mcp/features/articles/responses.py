from typing import Self

from pydantic import Field

from with_intelligence_mcp.features.articles.api_responses import (
    ArticleExtendedAttributes,
    ArticleFirmAttributes,
    ArticleListItemAttributes,
)
from with_intelligence_mcp.models import OmitNoneModel
from with_intelligence_mcp.utils import html_to_markdown


class ArticleFirmResponse(OmitNoneModel):
    entity_id: int | None = Field(
        default=None, description="With Intelligence id of the tagged firm."
    )
    type: str | None = Field(
        default=None,
        description=(
            "What the tagged firm is: institutional_investor, manager, consultant, or fund."
        ),
    )
    is_primary: bool | None = Field(
        default=None, description="Whether this firm is the article's primary subject."
    )


class ArticleResponse(OmitNoneModel):
    """One article mentioning a firm."""

    id: int = Field(description="With Intelligence article identifier.", examples=[100])
    title: str | None = Field(default=None, description="Article title.")
    published_at: str | None = Field(
        default=None,
        description="When the article was published. The page is not ordered by this.",
        examples=["2026-09-29T15:56:19"],
    )
    excerpt: str | None = Field(default=None, description="Article excerpt, as prose.")
    body: str | None = Field(
        default=None,
        description="Article body, as prose. A snippet may have only an excerpt.",
    )
    article_type: str | None = Field(
        default=None,
        description="With Intelligence's article type, such as Snippet or Regular.",
        examples=["Snippet"],
    )
    author: str | None = Field(default=None, description="Author display name.")
    document_url: str | None = Field(
        default=None, description="Link to an attached document, when the article has one."
    )
    document_title: str | None = Field(default=None, description="Title of the attached document.")
    firms: list[ArticleFirmResponse] | None = Field(
        default=None, description="Firms the article is tagged to."
    )

    @classmethod
    def from_attributes(cls, attributes: ArticleExtendedAttributes) -> Self:
        return cls(
            id=attributes.id,
            title=attributes.post_title,
            published_at=attributes.post_date,
            excerpt=html_to_markdown(attributes.post_excerpt),
            body=html_to_markdown(attributes.post_content),
            article_type=attributes.article_type.name if attributes.article_type else None,
            author=attributes.post_author.display_name if attributes.post_author else None,
            document_url=attributes.document.url if attributes.document else None,
            document_title=attributes.document.title if attributes.document else None,
            firms=(
                [_firm(entry) for entry in attributes.post_firms]
                if "post_firms" in attributes.model_fields_set and attributes.post_firms is not None
                else None
            ),
        )

    @classmethod
    def from_listing(cls, attributes: ArticleListItemAttributes) -> Self:
        return cls(id=attributes.id, title=attributes.post_title, published_at=attributes.post_date)


class InvestorArticlesResponse(OmitNoneModel):
    """Articles tagged to one investor.

    Order is With Intelligence's own. Read `published_at` rather than assuming the page is
    chronological. An empty list can mean nothing was tagged, or that this page is past the end.
    """

    investor_id: int = Field(description="With Intelligence investor identifier.")
    investor_name: str | None = Field(default=None, description="Resolved investor name.")
    articles: list[ArticleResponse] = Field(
        default_factory=list,
        description="Articles on this page. Read `published_at`; the page is not newest-first.",
    )
    total: int = Field(default=0, description="How many tagged articles With Intelligence holds.")
    returned: int = Field(default=0, description="Number of articles returned on this page.")
    page: int = Field(default=1, description="Page number represented by this response.")
    has_more: bool = Field(
        default=False,
        description="True when another page is available. Call again with page + 1.",
    )


def _firm(attributes: ArticleFirmAttributes) -> ArticleFirmResponse:
    return ArticleFirmResponse(
        entity_id=attributes.entity_id,
        type=attributes.type,
        is_primary=attributes.is_primary,
    )
