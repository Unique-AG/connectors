"""`get_articles`: tagged to the investor, excerpt as prose."""

import httpx
import respx

from tests.helpers import BASE_URL, build_client, page_body, sent_query, sent_records
from with_intelligence_mcp.features.articles import InvestorArticlesResponse
from with_intelligence_mcp.features.articles.queries import GetArticlesQuery
from with_intelligence_mcp.features.articles.tools.get_articles import (
    GetArticlesResult,
)
from with_intelligence_mcp.features.articles.tools.get_articles import (
    get_articles as call_get_articles,
)
from with_intelligence_mcp.features.investors.queries import ResolveInvestorRecordQuery
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient

INVESTOR: dict[str, object] = {"id": 2504, "name": "Example Retirement System (ERS)"}
ARTICLE: dict[str, object] = {
    "id": 100,
    "post_title": "Example portfolio update",
    "post_date": "2026-09-29T15:56:19",
    "post_excerpt": (
        '<sc_entity type="institutional_investor" id="2504">Example RS</sc_entity> returned 7%.'
    ),
    "post_content": "<p>The full note on Example RS.</p>",
    "article_type": {"id": 3, "name": "Snippet"},
    "post_author": {"id": 1, "display_name": "A. Writer"},
    "post_firms": [{"entity_id": 2504, "is_primary": True, "type": "institutional_investor"}],
}


async def get_articles(
    *,
    client: WithIntelligenceClient,
    investor_id: int | None = None,
    posted_since: str | None = None,
) -> GetArticlesResult:
    return await call_get_articles(
        investor_id=investor_id,
        posted_since=posted_since,
        resolve_investor_record_query=ResolveInvestorRecordQuery(client),
        get_articles_query=GetArticlesQuery(client=client),
    )


def _mock_investor() -> None:
    respx.get(f"{BASE_URL}/v3/investors/2504").mock(return_value=httpx.Response(200, json=INVESTOR))


class TestProjection:
    @respx.mock
    async def test_asks_for_articles_about_this_investor_and_strips_markup(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/articles").mock(
            return_value=httpx.Response(
                200,
                json=page_body(
                    [
                        {
                            "id": 100,
                            "post_title": "Example portfolio update",
                            "post_date": "2026-09-29",
                        }
                    ],
                    total=1,
                ),
            )
        )
        respx.get(f"{BASE_URL}/v3/articles/100").mock(
            return_value=httpx.Response(200, json=ARTICLE)
        )
        _mock_investor()
        client, _ = build_client()
        result = await get_articles(investor_id=2504, posted_since="2026-01-01", client=client)
        assert isinstance(result, InvestorArticlesResponse)
        query = sent_query(route)
        assert "firm_id=2504" in query
        assert "firm_type=institutional_investor" in query
        assert "post_date%5Bfrom%5D=2026-01-01" in query
        assert "sort%5Bid%5D=desc" in query
        article = result.results[0]
        assert article.title == "Example portfolio update"
        assert article.excerpt == "Example RS returned 7%."
        assert article.body == "The full note on Example RS."
        assert article.article_type == "Snippet"
        assert article.author == "A. Writer"
        assert article.firms is not None
        assert article.firms[0].entity_id == 2504
        assert article.firms[0].is_primary is True

    @respx.mock
    async def test_a_refused_detail_keeps_the_listing_title(self) -> None:
        respx.get(f"{BASE_URL}/v3/articles").mock(
            return_value=httpx.Response(
                200,
                json=page_body(
                    [{"id": 100, "post_title": "Listing title", "post_date": "2026-09-01"}],
                    total=1,
                ),
            )
        )
        respx.get(f"{BASE_URL}/v3/articles/100").mock(return_value=httpx.Response(403))
        _mock_investor()
        client, _ = build_client()
        result = await get_articles(investor_id=2504, client=client)
        assert isinstance(result, InvestorArticlesResponse)
        assert result.results[0].title == "Listing title"
        assert result.results[0].excerpt is None


class TestCitation:
    @respx.mock
    async def test_titles_each_article_under_results_and_never_cites_the_attachment(
        self,
    ) -> None:
        """The attachment is a download; a null `web_url` keeps it from being cited."""
        with_document = {
            **ARTICLE,
            "id": 101,
            "post_title": "Example quarterly letter",
            "document": {"url": "https://files.example.invalid/letter.pdf", "title": "Letter"},
        }
        respx.get(f"{BASE_URL}/v3/articles").mock(
            return_value=httpx.Response(200, json=page_body([{"id": 100}, {"id": 101}], total=2))
        )
        respx.get(f"{BASE_URL}/v3/articles/100").mock(
            return_value=httpx.Response(200, json=ARTICLE)
        )
        respx.get(f"{BASE_URL}/v3/articles/101").mock(
            return_value=httpx.Response(200, json=with_document)
        )
        _mock_investor()
        client, _ = build_client()
        result = await get_articles(investor_id=2504, client=client)
        assert isinstance(result, InvestorArticlesResponse)
        articles = sent_records(result)
        assert [article["title"] for article in articles] == [
            "Example portfolio update",
            "Example quarterly letter",
        ]
        assert [article["web_url"] for article in articles] == [None, None]
        assert articles[1]["document_url"] == "https://files.example.invalid/letter.pdf"
