from with_intelligence_mcp.utils import article_url, attachment_url


def test_an_article_slug_is_escaped_into_one_path_segment() -> None:
    assert article_url(7, "a/b c") == "https://platform.withintelligence.com/insights/a%2Fb%20c?a=7"


def test_an_attachment_outside_the_cms_uploads_is_kept_as_sent() -> None:
    assert attachment_url("https://example.invalid/pack.pdf") == "https://example.invalid/pack.pdf"
