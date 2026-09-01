"""Knowledge Base read-file tool — read a specific content's text, in full or by page range.

- CONFIG (admin): ReadFileToolConfig.max_tokens_per_call
- STATE (LLM): content_id required, start_page/end_page optional
"""

import logging
import math
from pathlib import Path
from typing import Annotated

import httpx
import tiktoken
from fastmcp.dependencies import Depends
from fastmcp.tools import ToolResult, tool
from mcp.types import TextContent, ToolAnnotations
from pydantic import Field
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
from unique_mcp import (
    ConfigSchemaMeta,
    ContextRequirements,
    MetaKeys,
    get_tool_config,
    get_unique_settings_async,
    merge_tool_meta,
)
from unique_toolkit._common.token.token_counting import DEFAULT_ENCODING, count_tokens
from unique_toolkit.content.functions import (
    download_content_to_bytes_async,
    search_contents_async,
)
from unique_toolkit.content.schemas import Content, ContentChunk
from unique_toolkit.content.utils import sort_content_chunks

from kb_mcp.correlation import correlation_id
from kb_mcp.references import file_reference_url, markdown_citation_link
from kb_mcp.settings import get_settings
from kb_mcp.tools.read_file.config import ReadFileToolConfig

_LOGGER = logging.getLogger(__name__)

_TEXT_EXTENSIONS = {".txt", ".md", ".html", ".json", ".csv", ".vtt"}
_CHUNKED_EXTENSIONS = {".pdf", ".docx"}

# The only two formats with a page-aware extraction pipeline; everything
# else that decodes cleanly enough gets the flat-text path instead.
_CHUNKED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _is_chunked(content: Content) -> bool | None:
    """True (chunked), False (flat text), or None (unsupported).

    Prefers mime_type over the key's extension — a transcript's key is an
    opaque recording id, not a filename. Any text/* mime type counts as
    flat text (the decode already degrades on bad bytes, so an unlisted
    subtype is still safe); application/json is the one exception.
    """
    mime = content.mime_type
    if mime in _CHUNKED_MIME_TYPES:
        return True
    if mime == "application/json" or (mime is not None and mime.startswith("text/")):
        return False

    suffix = Path(content.key).suffix.lower()
    if suffix in _CHUNKED_EXTENSIONS:
        return True
    if suffix in _TEXT_EXTENSIONS:
        return False
    return None


_META = merge_tool_meta(
    {
        "unique.app/icon": "file-text",
        "unique.app/system-prompt": (
            "Choose this tool to read the contents of a specific file once "
            "you have its content_id (e.g. from content_tree)."
        ),
    },
    ContextRequirements(
        required=[MetaKeys.USER_ID, MetaKeys.COMPANY_ID],
    ),
    ConfigSchemaMeta(ReadFileToolConfig),
)


def _render_chunked(
    chunks: list[ContentChunk],
    start_page: int | None,
    end_page: int | None,
    max_tokens_per_call: int,
) -> tuple[bool, str]:
    """Return ``(is_error, text)``."""
    if not chunks:
        return True, "this file hasn't finished processing yet"

    total_pages = max((c.end_page or c.start_page or 0) for c in chunks)
    if total_pages == 0:
        # No page metadata (some DOCX pipelines) — virtual pages instead.
        full_text = "\n".join(c.text for c in chunks)
        return _render_text(full_text, start_page, end_page, max_tokens_per_call)

    if start_page is None and end_page is None:
        full_text = "\n".join(c.text for c in chunks)
        total_tokens = count_tokens(full_text)
        if total_tokens <= max_tokens_per_call:
            return False, _render_with_page_markers(chunks)
        return True, (
            f"file has ~{total_tokens} tokens across {total_pages} pages; "
            "specify start_page/end_page to read a portion."
        )

    s = start_page if start_page is not None else 1
    e = end_page if end_page is not None else total_pages
    if s < 1 or s > e or s > total_pages:
        return True, (
            f"file has {total_pages} pages; requested range {s}-{e} is out of bounds."
        )

    selected = [
        c
        for c in chunks
        if (c.start_page or 0) <= e and (c.end_page or c.start_page or 0) >= s
    ]
    if not selected:
        return True, (
            f"no content found in pages {s}-{e}; the file's page numbering "
            "may have gaps — try a wider range."
        )

    text = _render_with_page_markers(selected)
    # Single-page requests always succeed even if one page exceeds the token cap.
    if s < e:
        selected_tokens = count_tokens(text)
        if selected_tokens > max_tokens_per_call:
            return True, (
                f"pages {s}-{e} span ~{selected_tokens} tokens, over the "
                f"{max_tokens_per_call}-token per-call limit; request a "
                "narrower range (a single page is always allowed)."
            )
    return False, text


def _render_with_page_markers(chunks: list[ContentChunk]) -> str:
    parts: list[str] = []
    last_page: int | None = None
    for c in chunks:
        if c.start_page is not None and c.start_page != last_page:
            parts.append(f"--- page {c.start_page} ---")
            last_page = c.start_page
        parts.append(c.text)
    return "\n".join(parts)


def _render_text(
    full_text: str,
    start_page: int | None,
    end_page: int | None,
    max_tokens_per_call: int,
) -> tuple[bool, str]:
    """Return ``(is_error, text)``."""
    total_tokens = count_tokens(full_text)
    total_pages = max(1, math.ceil(total_tokens / max_tokens_per_call))

    if start_page is None and end_page is None:
        if total_tokens <= max_tokens_per_call:
            return False, full_text
        return True, (
            f"file has ~{total_tokens} tokens (~{total_pages} pages of "
            f"{max_tokens_per_call} tokens each); specify start_page/end_page "
            "to read a portion."
        )

    s = start_page if start_page is not None else 1
    e = end_page if end_page is not None else total_pages
    if s < 1 or s > e or s > total_pages:
        return True, (
            f"file has {total_pages} pages; requested range {s}-{e} is out of bounds."
        )
    # Virtual pages are sized to max_tokens_per_call, so multi-page ranges overflow.
    if s < e:
        return True, (
            f"each virtual page is {max_tokens_per_call} tokens (the per-call "
            f"limit); read one page per call. File has {total_pages} pages."
        )

    token_start, token_end = _virtual_page_token_bounds(s, e, max_tokens_per_call)
    slice_text = _slice_by_token_count(full_text, token_start, token_end)
    prefix = f"showing tokens {token_start}-{token_end} of {total_tokens} total"
    return False, f"{prefix}\n\n{slice_text}"


def _slice_by_token_count(text: str, token_start: int, token_end: int) -> str:
    encoder = tiktoken.get_encoding(DEFAULT_ENCODING)
    token_ids = encoder.encode(text)
    return encoder.decode(token_ids[token_start:token_end])


def _virtual_page_token_bounds(
    start_page: int, end_page: int, max_tokens_per_call: int
) -> tuple[int, int]:
    token_start = (start_page - 1) * max_tokens_per_call
    token_end = end_page * max_tokens_per_call
    return token_start, token_end


def _is_transient_download_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


@retry(
    retry=retry_if_exception(_is_transient_download_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, max=4),
    reraise=True,
)
async def _download_with_retry(
    *, user_id: str, company_id: str, content_id: str, chat_id: str | None
) -> bytes:
    return await download_content_to_bytes_async(
        user_id=user_id, company_id=company_id, content_id=content_id, chat_id=chat_id
    )


@tool(
    name="read_file",
    meta=_META,
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def read_file(
    content_id: Annotated[
        str,
        Field(description="The content_id of the file to read, from content_tree."),
    ],
    start_page: Annotated[
        int | None,
        Field(
            description=(
                "First page to return (1-indexed). Real document page for "
                "PDF/DOCX, virtual token-based page for plain-text formats."
            )
        ),
    ] = None,
    end_page: Annotated[
        int | None,
        Field(description="Last page to return (1-indexed), inclusive."),
    ] = None,
    config: ReadFileToolConfig = Depends(get_tool_config(ReadFileToolConfig)),
) -> ToolResult:
    """Read a specific knowledge-base file's text content. Requires
    `content_id` (from a prior content_tree 'list'/'search' call).
    For large files, pass `start_page`/`end_page` to read a portion — for
    PDFs/DOCX these are real document pages; for plain-text formats
    (.txt/.md/.html/.json/.csv/.vtt) they're fixed-size virtual pages, same
    semantics either way. If the file is too large and no range is given,
    the call returns an informative error (with the file's total token/page
    count) instead of silently truncating — use that to pick a range. Ranges
    are also token-capped; if a range is too large, narrow it (a single-page
    request always succeeds). Successful reads start with a markdown link
    that opens the file in the Unique knowledge base — paste it as-is when
    citing the file.
    """
    kb_settings = get_settings()
    cid: str | None = None
    try:
        # In-body (not Depends) so identity-refusal ValueError surfaces as a tool error.
        settings = await get_unique_settings_async()
        company_id = settings.authcontext.get_confidential_company_id()
        user_id = settings.authcontext.get_confidential_user_id()
        cid = correlation_id(user_id, company_id)
        _LOGGER.info("read_file start correlation_id=%s content_id=%s", cid, content_id)

        contents = await search_contents_async(
            user_id=user_id,
            company_id=company_id,
            chat_id=None,
            where={"id": {"equals": content_id}},
        )
        if not contents:
            _LOGGER.info(
                "read_file complete correlation_id=%s content_id=%s is_error=True "
                "reason=not_found",
                cid,
                content_id,
            )
            return ToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"no content found for content_id={content_id}",
                    )
                ],
                is_error=True,
            )
        content = contents[0]

        is_chunked = _is_chunked(content)
        if is_chunked is None:
            suffix = Path(content.key).suffix
            _LOGGER.info(
                "read_file complete correlation_id=%s content_id=%s is_error=True "
                "reason=unsupported_file_type mime_type=%s",
                cid,
                content_id,
                content.mime_type,
            )
            detail = f" (mime_type={content.mime_type})" if content.mime_type else ""
            return ToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"unsupported file type for read_file: {suffix}{detail}",
                    )
                ],
                is_error=True,
            )

        if is_chunked:
            chunks = sort_content_chunks(list(content.chunks))
            is_error, text = _render_chunked(
                chunks, start_page, end_page, config.max_tokens_per_call
            )
        else:
            try:
                raw_bytes = await _download_with_retry(
                    user_id=user_id,
                    company_id=company_id,
                    content_id=content_id,
                    chat_id=None,
                )
                full_text = raw_bytes.decode("utf-8", errors="replace")
            except httpx.HTTPStatusError as exc:
                # Scraped/crawled content (e.g. a Confluence page) has no
                # downloadable file at all — only chunks from ingestion —
                # so a 404 here falls back to them instead of failing.
                if exc.response.status_code != 404 or not content.chunks:
                    raise
                chunks = sort_content_chunks(list(content.chunks))
                full_text = "\n".join(c.text for c in chunks)
            is_error, text = _render_text(
                full_text, start_page, end_page, config.max_tokens_per_call
            )

        _LOGGER.info(
            "read_file complete correlation_id=%s content_id=%s is_error=%s",
            cid,
            content_id,
            is_error,
        )
        if is_error:
            return ToolResult(
                content=[TextContent(type="text", text=text)], is_error=True
            )

        url = file_reference_url(
            content.id,
            metadata=content.metadata,
            frontend_base_url=kb_settings.frontend_base_url_str(),
        )
        header = markdown_citation_link(content.title or content.key, url)
        return ToolResult(
            content=[TextContent(type="text", text=f"{header}\n\n{text}")]
        )
    except Exception as exc:
        _LOGGER.exception(
            "read_file error correlation_id=%s content_id=%s error_type=%s",
            cid,
            content_id,
            type(exc).__name__,
        )
        return ToolResult(
            content=[TextContent(type="text", text=str(exc))], is_error=True
        )
