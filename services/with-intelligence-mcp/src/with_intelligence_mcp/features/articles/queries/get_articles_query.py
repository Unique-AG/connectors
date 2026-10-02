import asyncio
import logging

from pydantic import TypeAdapter

from with_intelligence_mcp.features.articles.api_responses import (
    ArticleExtendedAttributes,
    ArticleListItemAttributes,
)
from with_intelligence_mcp.features.articles.responses import (
    ArticleResponse,
    InvestorArticlesResponse,
)
from with_intelligence_mcp.features.investors.api_responses import InvestorExtendedAttributes
from with_intelligence_mcp.with_intelligence_client import (
    NotEntitled,
    NotFound,
    Page,
    QueryValue,
    WithIntelligenceClient,
)

logger = logging.getLogger(__name__)
_ARTICLE = TypeAdapter(ArticleExtendedAttributes)
_ARTICLES_PAGE = TypeAdapter(Page[ArticleListItemAttributes])


class GetArticlesQuery:
    def __init__(self, *, client: WithIntelligenceClient) -> None:
        self._client: WithIntelligenceClient = client

    async def run(
        self,
        *,
        investor: InvestorExtendedAttributes,
        page: int,
        limit: int,
        posted_since: str | None,
    ) -> InvestorArticlesResponse:
        listed, total = await self._list_articles(
            investor_id=investor.id,
            page=page,
            limit=limit,
            posted_since=posted_since,
        )
        details = await asyncio.gather(*(self._fetch_article(entry.id) for entry in listed))
        articles = [
            ArticleResponse.from_attributes(detail)
            if detail
            else ArticleResponse.from_listing(listed[index])
            for index, detail in enumerate(details)
        ]
        response = InvestorArticlesResponse(
            investor_id=investor.id,
            investor_name=investor.name,
            articles=articles,
            total=total,
            returned=len(articles),
            page=page,
            has_more=(page - 1) * limit + len(articles) < total,
        )
        logger.info(
            "articles.investor.fetched",
            extra={"investor_id": investor.id, "returned": response.returned, "total": total},
        )
        return response

    async def _fetch_article(self, article_id: int) -> ArticleExtendedAttributes | None:
        try:
            return await self._client.get_json(f"/v3/articles/{article_id}", _ARTICLE)
        except NotEntitled, NotFound:
            return None

    async def _list_articles(
        self,
        *,
        investor_id: int,
        page: int,
        limit: int,
        posted_since: str | None,
    ) -> tuple[list[ArticleListItemAttributes], int]:
        params: dict[str, QueryValue] = {
            "firm_id": [investor_id],
            "firm_type": ["institutional_investor"],
        }
        if posted_since is not None:
            params["post_date[from]"] = posted_since
        response = await self._client.get_page(
            "/v3/articles",
            _ARTICLES_PAGE,
            params,
            page=page,
            page_size=limit,
        )
        return response.results, response.pagination.total
