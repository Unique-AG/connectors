"""Tests for the read_file tool — extension dispatch, size cutoff, page ranges."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from unique_toolkit.content.schemas import Content, ContentChunk

from kb_mcp.tools.read_file import ReadFileToolConfig, read_file
from kb_mcp.tools.read_file.tool import _download_with_retry

pytestmark = pytest.mark.ai


def _make_settings(company_id: str = "company-1", user_id: str = "user-1"):
    settings = MagicMock()
    settings.authcontext.get_confidential_company_id.return_value = company_id
    settings.authcontext.get_confidential_user_id.return_value = user_id
    return settings


@pytest.fixture(autouse=True)
def _identity(monkeypatch):
    """Per-request identity now resolves in-body via unique_mcp."""
    monkeypatch.setattr(
        "kb_mcp.tools.read_file.tool.get_unique_settings_async",
        AsyncMock(return_value=_make_settings()),
    )


def _make_content(
    key: str,
    chunks: list[ContentChunk] | None = None,
    mime_type: str | None = None,
) -> Content:
    return Content(
        id="cont_abc", key=key, chunks=chunks or [], metadata=None, mime_type=mime_type
    )


def _make_chunk(text: str, order: int, start_page: int, end_page: int) -> ContentChunk:
    return ContentChunk(
        id="cont_abc",
        text=text,
        order=order,
        start_page=start_page,
        end_page=end_page,
    )


def _patch_search_contents(content: Content):
    return patch(
        "kb_mcp.tools.read_file.tool.search_contents_async",
        AsyncMock(return_value=[content]),
    )


def _patch_download(data: bytes):
    return patch(
        "kb_mcp.tools.read_file.tool.download_content_to_bytes_async",
        AsyncMock(return_value=data),
    )


def _patch_download_error(status_code: int):
    request = httpx.Request("GET", "https://example.test/content/cont_abc/file")
    response = httpx.Response(status_code, request=request)
    error = httpx.HTTPStatusError("boom", request=request, response=response)
    return patch(
        "kb_mcp.tools.read_file.tool.download_content_to_bytes_async",
        AsyncMock(side_effect=error),
    )


def _patch_no_retry_delay():
    return patch.object(_download_with_retry.retry, "sleep", AsyncMock())


@pytest.mark.asyncio
async def test_unsupported_extension_returns_error_without_downstream_calls():
    content = _make_content("report.xlsx")
    with (
        _patch_search_contents(content),
        patch(
            "kb_mcp.tools.read_file.tool.download_content_to_bytes_async"
        ) as mock_download,
    ):
        result = await read_file(
            content_id="cont_abc",
            config=ReadFileToolConfig(),
        )

    assert result.is_error is True
    assert "unsupported file type for read_file: .xlsx" in result.content[0].text  # type: ignore[union-attr]
    mock_download.assert_not_called()


@pytest.mark.asyncio
async def test_unsupported_mime_type_is_named_in_the_error():
    content = _make_content("report.xlsx", mime_type="application/vnd.ms-excel")
    with _patch_search_contents(content):
        result = await read_file(content_id="cont_abc", config=ReadFileToolConfig())

    assert result.is_error is True
    text = result.content[0].text  # type: ignore[union-attr]
    assert "unsupported file type for read_file: .xlsx" in text
    assert "mime_type=application/vnd.ms-excel" in text


@pytest.mark.asyncio
async def test_mime_type_resolves_text_when_key_has_no_extension():
    """A call/video transcript's key is an opaque recording id, not a
    filename — mime_type is the only signal available."""
    content = _make_content("a6ughlz4rlbz3jszsqzhbatb", mime_type="text/vtt")
    with (
        _patch_search_contents(content),
        _patch_download(b"WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello.\n"),
    ):
        result = await read_file(content_id="cont_abc", config=ReadFileToolConfig())

    assert result.is_error is not True
    text = result.content[0].text  # type: ignore[union-attr]
    assert "WEBVTT" in text
    assert "Hello." in text


@pytest.mark.asyncio
async def test_mime_type_resolves_html_when_key_is_a_source_url():
    """A scraped page's key is its source URL, not a filename."""
    content = _make_content(
        "https://unique-ch.atlassian.net/731283492", mime_type="text/html"
    )
    with (
        _patch_search_contents(content),
        _patch_download(b"<html><body>hi</body></html>"),
    ):
        result = await read_file(content_id="cont_abc", config=ReadFileToolConfig())

    assert result.is_error is not True
    assert "<html><body>hi</body></html>" in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_download_404_falls_back_to_chunk_text_when_available():
    """Scraped/crawled content has no downloadable file, only chunks."""
    chunks = [_make_chunk("page text from ingestion", 0, 1, 1)]
    content = _make_content(
        "https://unique-ch.atlassian.net/731283492", chunks, mime_type="text/html"
    )
    with _patch_search_contents(content), _patch_download_error(404):
        result = await read_file(content_id="cont_abc", config=ReadFileToolConfig())

    assert result.is_error is not True
    assert "page text from ingestion" in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_download_404_without_chunks_still_errors():
    content = _make_content("https://example.com/page", mime_type="text/html")
    with _patch_search_contents(content), _patch_download_error(404):
        result = await read_file(content_id="cont_abc", config=ReadFileToolConfig())

    assert result.is_error is True


@pytest.mark.asyncio
async def test_download_non_404_error_is_not_swallowed_by_chunk_fallback():
    chunks = [_make_chunk("page text from ingestion", 0, 1, 1)]
    content = _make_content("https://example.com/page", chunks, mime_type="text/html")
    with (
        _patch_search_contents(content),
        _patch_download_error(500),
        _patch_no_retry_delay(),
    ):
        result = await read_file(content_id="cont_abc", config=ReadFileToolConfig())

    assert result.is_error is True
    assert "page text from ingestion" not in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_transient_download_error_retries_then_succeeds():
    content = _make_content("notes.txt")
    request = httpx.Request("GET", "https://example.test/content/cont_abc/file")
    with (
        _patch_search_contents(content),
        patch(
            "kb_mcp.tools.read_file.tool.download_content_to_bytes_async",
            AsyncMock(
                side_effect=[httpx.ReadTimeout("boom", request=request), b"recovered"]
            ),
        ),
        _patch_no_retry_delay(),
    ):
        result = await read_file(content_id="cont_abc", config=ReadFileToolConfig())

    assert result.is_error is not True
    assert "recovered" in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_unrecognized_text_mime_subtype_is_treated_as_text():
    """text/* is matched broadly, not from an enumerated set of subtypes —
    covers legitimate but unlisted subtypes like text/calendar."""
    content = _make_content("invite.ics", mime_type="text/calendar")
    with (
        _patch_search_contents(content),
        _patch_download(b"BEGIN:VCALENDAR\nEND:VCALENDAR"),
    ):
        result = await read_file(content_id="cont_abc", config=ReadFileToolConfig())

    assert result.is_error is not True
    assert "BEGIN:VCALENDAR" in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_mime_type_takes_precedence_over_a_mismatched_extension():
    """Covers the real case where an upload's key still carries a stale
    or wrong extension."""
    content = _make_content("upload.bin", mime_type="text/plain")
    with (
        _patch_search_contents(content),
        _patch_download(b"just plain text"),
    ):
        result = await read_file(content_id="cont_abc", config=ReadFileToolConfig())

    assert result.is_error is not True
    assert "just plain text" in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_json_mime_type_is_supported_despite_not_being_under_text():
    content = _make_content("cont_opaque_key", mime_type="application/json")
    with (
        _patch_search_contents(content),
        _patch_download(b'{"a": 1}'),
    ):
        result = await read_file(content_id="cont_abc", config=ReadFileToolConfig())

    assert result.is_error is not True
    assert '{"a": 1}' in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_chunked_mime_type_dispatches_to_page_aware_rendering():
    chunks = [_make_chunk("hello", 0, 1, 1)]
    content = _make_content("cont_opaque_key", chunks, mime_type="application/pdf")
    with (
        _patch_search_contents(content),
        patch(
            "kb_mcp.tools.read_file.tool.download_content_to_bytes_async"
        ) as mock_download,
    ):
        result = await read_file(content_id="cont_abc", config=ReadFileToolConfig())

    assert result.is_error is not True
    assert "--- page 1 ---" in result.content[0].text  # type: ignore[union-attr]
    mock_download.assert_not_called()


@pytest.mark.asyncio
async def test_no_content_found_returns_error_without_downstream_calls():
    with (
        patch(
            "kb_mcp.tools.read_file.tool.search_contents_async",
            AsyncMock(return_value=[]),
        ),
        patch(
            "kb_mcp.tools.read_file.tool.download_content_to_bytes_async"
        ) as mock_download,
    ):
        result = await read_file(
            content_id="cont_missing",
            config=ReadFileToolConfig(),
        )

    assert result.is_error is True
    assert "no content found for content_id=cont_missing" in result.content[0].text  # type: ignore[union-attr]
    mock_download.assert_not_called()


@pytest.mark.asyncio
async def test_logs_never_contain_raw_user_or_company_id(caplog):
    """user_id/company_id are confidential; logs must carry a correlation
    id derived from them, never the raw values."""
    content = _make_content("report.xlsx")
    with (
        caplog.at_level(logging.INFO, logger="kb_mcp"),
        _patch_search_contents(content),
    ):
        await read_file(content_id="cont_abc", config=ReadFileToolConfig())

    assert caplog.records, "expected at least one log record"
    for record in caplog.records:
        assert "user-1" not in record.getMessage()
        assert "company-1" not in record.getMessage()


@pytest.mark.asyncio
async def test_chunked_small_doc_returns_full_text_with_page_markers():
    chunks = [
        _make_chunk("hello ", 0, 1, 1),
        _make_chunk("world", 1, 2, 2),
    ]
    content = _make_content("doc.pdf", chunks)
    with _patch_search_contents(content) as mock_search:
        result = await read_file(
            content_id="cont_abc",
            config=ReadFileToolConfig(max_tokens_per_call=8_000),
        )

    mock_search.assert_awaited_once()
    _, kwargs = mock_search.call_args
    assert kwargs["where"] == {"id": {"equals": "cont_abc"}}
    assert result.is_error is not True
    text = result.content[0].text  # type: ignore[union-attr]
    assert "--- page 1 ---" in text
    assert "--- page 2 ---" in text
    assert "hello" in text and "world" in text


@pytest.mark.asyncio
async def test_chunked_oversized_no_range_returns_informative_error():
    big_text = "word " * 20_000
    chunks = [_make_chunk(big_text, 0, 1, 100)]
    content = _make_content("doc.pdf", chunks)
    with _patch_search_contents(content):
        result = await read_file(
            content_id="cont_abc",
            config=ReadFileToolConfig(max_tokens_per_call=10),
        )

    assert result.is_error is True
    text = result.content[0].text  # type: ignore[union-attr]
    assert "tokens" in text
    assert "100 pages" in text
    assert "start_page/end_page" in text


@pytest.mark.asyncio
async def test_chunked_multi_page_range_over_cap_returns_error():
    huge_text = "word " * 50_000
    chunks = [
        _make_chunk("short intro", 0, 1, 1),
        _make_chunk(huge_text, 1, 2, 5),
    ]
    content = _make_content("doc.pdf", chunks)
    with _patch_search_contents(content):
        result = await read_file(
            content_id="cont_abc",
            start_page=2,
            end_page=5,
            config=ReadFileToolConfig(max_tokens_per_call=10),
        )

    assert result.is_error is True
    text = result.content[0].text  # type: ignore[union-attr]
    assert "narrower range" in text
    assert "per-call limit" in text


@pytest.mark.asyncio
async def test_chunked_single_page_request_exempt_from_cap():
    """A single page must stay readable even when it alone exceeds the cap."""
    huge_text = "word " * 50_000
    chunks = [
        _make_chunk("short intro", 0, 1, 1),
        _make_chunk(huge_text, 1, 2, 5),
    ]
    content = _make_content("doc.pdf", chunks)
    with _patch_search_contents(content):
        result = await read_file(
            content_id="cont_abc",
            start_page=2,
            end_page=2,
            config=ReadFileToolConfig(max_tokens_per_call=10),
        )

    assert result.is_error is not True
    text = result.content[0].text  # type: ignore[union-attr]
    assert "word" in text
    assert "short intro" not in text


@pytest.mark.asyncio
async def test_chunked_start_page_zero_is_out_of_bounds():
    chunks = [_make_chunk("hello", 0, 1, 5)]
    content = _make_content("doc.pdf", chunks)
    with _patch_search_contents(content):
        result = await read_file(
            content_id="cont_abc",
            start_page=0,
            end_page=2,
            config=ReadFileToolConfig(),
        )

    assert result.is_error is True
    assert "out of bounds" in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_chunked_page_gap_range_returns_no_content_error():
    chunks = [
        _make_chunk("first", 0, 1, 1),
        _make_chunk("last", 1, 5, 5),
    ]
    content = _make_content("doc.pdf", chunks)
    with _patch_search_contents(content):
        result = await read_file(
            content_id="cont_abc",
            start_page=2,
            end_page=3,
            config=ReadFileToolConfig(),
        )

    assert result.is_error is True
    assert "no content found in pages 2-3" in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_chunked_without_page_metadata_falls_back_to_virtual_paging():
    """Chunks with no page numbers (some DOCX pipelines) must not dead-end
    on 'file has 0 pages' — they fall back to text-style virtual paging."""
    chunks = [
        ContentChunk(id="cont_abc", text="alpha beta", order=0),
        ContentChunk(id="cont_abc", text="gamma delta", order=1),
    ]
    content = _make_content("doc.docx", chunks)
    with _patch_search_contents(content):
        result = await read_file(
            content_id="cont_abc",
            config=ReadFileToolConfig(max_tokens_per_call=8_000),
        )

    assert result.is_error is not True
    text = result.content[0].text  # type: ignore[union-attr]
    assert "alpha beta" in text
    assert "gamma delta" in text


@pytest.mark.asyncio
async def test_chunked_out_of_bounds_range_returns_short_error():
    chunks = [_make_chunk("hello", 0, 1, 5)]
    content = _make_content("doc.pdf", chunks)
    with _patch_search_contents(content):
        result = await read_file(
            content_id="cont_abc",
            start_page=500,
            end_page=510,
            config=ReadFileToolConfig(),
        )

    assert result.is_error is True
    text = result.content[0].text  # type: ignore[union-attr]
    assert "5 pages" in text
    assert "500-510" in text
    assert "out of bounds" in text


@pytest.mark.asyncio
async def test_chunked_empty_chunks_returns_not_finished_processing_error():
    content = _make_content("doc.pdf", [])
    with _patch_search_contents(content):
        result = await read_file(
            content_id="cont_abc",
            config=ReadFileToolConfig(),
        )

    assert result.is_error is True
    assert "hasn't finished processing yet" in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_text_small_doc_returns_full_text_no_markers_no_page_language():
    content = _make_content("notes.md")
    with (
        _patch_search_contents(content),
        _patch_download(b"# Title\n\nSome short markdown content."),
    ):
        result = await read_file(
            content_id="cont_abc",
            config=ReadFileToolConfig(max_tokens_per_call=8_000),
        )

    assert result.is_error is not True
    text = result.content[0].text  # type: ignore[union-attr]
    assert text == (
        "[notes.md](unique://content/cont_abc)\n\n"
        "# Title\n\nSome short markdown content."
    )
    assert "--- page" not in text


@pytest.mark.asyncio
async def test_text_oversized_no_range_returns_virtual_page_error():
    big_text = "word " * 20_000
    content = _make_content("notes.txt")
    with (
        _patch_search_contents(content),
        _patch_download(big_text.encode("utf-8")),
    ):
        result = await read_file(
            content_id="cont_abc",
            config=ReadFileToolConfig(max_tokens_per_call=10),
        )

    assert result.is_error is True
    text = result.content[0].text  # type: ignore[union-attr]
    assert "tokens" in text
    assert "pages of 10 tokens each" in text
    assert "start_page/end_page" in text


@pytest.mark.asyncio
async def test_text_range_given_returns_token_boundary_slice_with_prefix():
    big_text = "word " * 20_000
    content = _make_content("notes.txt")
    with (
        _patch_search_contents(content),
        _patch_download(big_text.encode("utf-8")),
    ):
        result = await read_file(
            content_id="cont_abc",
            start_page=1,
            end_page=1,
            config=ReadFileToolConfig(max_tokens_per_call=10),
        )

    assert result.is_error is not True
    text = result.content[0].text  # type: ignore[union-attr]
    assert text.startswith("[notes.txt](unique://content/cont_abc)\n\n")
    assert "showing tokens 0-10 of" in text
    assert "word" in text


@pytest.mark.asyncio
async def test_text_out_of_bounds_range_returns_short_error():
    content = _make_content("notes.txt")
    with (
        _patch_search_contents(content),
        _patch_download(b"short text"),
    ):
        result = await read_file(
            content_id="cont_abc",
            start_page=50,
            end_page=60,
            config=ReadFileToolConfig(max_tokens_per_call=8_000),
        )

    assert result.is_error is True
    text = result.content[0].text  # type: ignore[union-attr]
    assert "out of bounds" in text


@pytest.mark.asyncio
async def test_text_start_page_zero_is_out_of_bounds():
    big_text = "word " * 20_000
    content = _make_content("notes.txt")
    with (
        _patch_search_contents(content),
        _patch_download(big_text.encode("utf-8")),
    ):
        result = await read_file(
            content_id="cont_abc",
            start_page=0,
            end_page=1,
            config=ReadFileToolConfig(max_tokens_per_call=10),
        )

    assert result.is_error is True
    assert "out of bounds" in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_text_multi_page_range_returns_one_page_per_call_error():
    big_text = "word " * 20_000
    content = _make_content("notes.txt")
    with (
        _patch_search_contents(content),
        _patch_download(big_text.encode("utf-8")),
    ):
        result = await read_file(
            content_id="cont_abc",
            start_page=1,
            end_page=3,
            config=ReadFileToolConfig(max_tokens_per_call=10),
        )

    assert result.is_error is True
    assert "one page per call" in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_text_non_utf8_bytes_degrade_instead_of_failing():
    content = _make_content("legacy.csv")
    with (
        _patch_search_contents(content),
        _patch_download(b"caf\xe9,ol\xe9\n"),  # latin-1, invalid UTF-8
    ):
        result = await read_file(
            content_id="cont_abc",
            config=ReadFileToolConfig(),
        )

    assert result.is_error is not True
    text = result.content[0].text  # type: ignore[union-attr]
    assert "caf" in text and "ol" in text


@pytest.mark.asyncio
async def test_identity_refusal_surfaces_as_tool_error(monkeypatch):
    monkeypatch.setattr(
        "kb_mcp.tools.read_file.tool.get_unique_settings_async",
        AsyncMock(side_effect=ValueError("Refusing UNIQUE_AUTH_* env fallback")),
    )
    result = await read_file(content_id="cont_abc", config=ReadFileToolConfig())

    assert result.is_error is True
    assert "UNIQUE_AUTH_" in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_successful_read_starts_with_reference_link():
    chunks = [_make_chunk("hello", 0, 1, 1)]
    content = _make_content("doc.pdf", chunks)
    with _patch_search_contents(content):
        result = await read_file(content_id="cont_abc", config=ReadFileToolConfig())

    text = result.content[0].text  # type: ignore[union-attr]
    assert text.startswith("[doc.pdf](unique://content/cont_abc)\n\n")
