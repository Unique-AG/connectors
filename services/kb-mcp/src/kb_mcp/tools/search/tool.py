"""Knowledge Base Search tool.

Separation of concerns:
- CONFIG  (admin-set, injected via the config meta key at call time)
  → service_config: KnowledgeBaseInternalSearchConfig — all retrieval params
  → post_processing: PostProcessorConfig — token budget, client-side reranking
  → no LLM involvement
- STATE   (LLM fills at call time, tool arguments)
  → search_string   required — what to search for
"""

import logging
from typing import Annotated, cast

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import CallToolResult, ContentBlock, TextContent, ToolAnnotations
from pydantic import Field
from unique_mcp import (
    ConfigSchemaMeta,
    ContextRequirements,
    MetaKeys,
    get_tool_config,
    get_unique_settings_async,
    merge_tool_meta,
)
from unique_toolkit.experimental.components.internal_search import (
    InternalSearchPostProcessor,
    KnowledgeBaseInternalSearchService,
)

from kb_mcp.correlation import correlation_id
from kb_mcp.references import (
    REFERENCE_FORMAT_INFORMATION,
    chunk_to_text_content,
    citation_instruction_content,
)
from kb_mcp.settings import get_settings
from kb_mcp.tools.search.config import SearchToolConfig
from kb_mcp.tools.search.scope_resolver import resolve_scope_ids

_LOGGER = logging.getLogger(__name__)

_META = merge_tool_meta(
    {
        "unique.app/icon": "search",
        "unique.app/system-prompt": (
            "Choose this tool if you need to search in the knowledge base. "
            + REFERENCE_FORMAT_INFORMATION
        ),
        "unique.app/tool-format-information": REFERENCE_FORMAT_INFORMATION,
    },
    ContextRequirements(
        required=[MetaKeys.USER_ID, MetaKeys.COMPANY_ID],
    ),
    ConfigSchemaMeta(SearchToolConfig),
)


@tool(
    name="search",
    # Not the docstring: this reuses REFERENCE_FORMAT_INFORMATION (also in
    # _META below), and a literal docstring can't reference a module constant.
    description=(
        "Search the knowledge base for the given query and return relevant "
        "chunks. " + REFERENCE_FORMAT_INFORMATION
    ),
    meta=_META,
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def search(
    search_string: Annotated[
        str,
        Field(description="The query to search for in the knowledge base."),
    ],
    config: SearchToolConfig = Depends(get_tool_config(SearchToolConfig)),
) -> CallToolResult:
    """Search the knowledge base using ``SearchToolConfig`` from the config meta key."""
    kb_settings = get_settings()
    cid: str | None = None

    try:
        # In-body (not Depends) so identity-refusal ValueError surfaces as a tool error.
        settings = await get_unique_settings_async()
        cid = correlation_id(
            settings.authcontext.get_confidential_user_id(),
            settings.authcontext.get_confidential_company_id(),
        )
        _LOGGER.info("search start correlation_id=%s", cid)

        service = KnowledgeBaseInternalSearchService.from_config(
            config.service_config
        ).bind_settings(settings)
        service.state.search_queries = [search_string]

        result = await service.run()

        post_processor = InternalSearchPostProcessor.from_settings(
            settings, config=config.post_processing
        )
        chunks = await post_processor.process(result)
    except Exception as exc:
        _LOGGER.exception(
            "search error correlation_id=%s error_type=%s", cid, type(exc).__name__
        )
        return CallToolResult(
            isError=True, content=[TextContent(type="text", text=str(exc))]
        )

    frontend_base_url = kb_settings.frontend_base_url_str()
    scope_by_content_id: dict[str, str] = {}
    if frontend_base_url and chunks:
        try:
            scope_by_content_id = await resolve_scope_ids(
                chunks,
                settings,
                lookup_concurrency=kb_settings.scope_lookup_concurrency,
            )
        except Exception:
            _LOGGER.exception("scope resolution failed; falling back to unique:// URLs")

    content: list[TextContent] = [
        chunk_to_text_content(
            chunk,
            sequence_number=i,
            frontend_base_url=frontend_base_url,
            scope_id=scope_by_content_id.get(chunk.id) if chunk.id else None,
        )
        for i, chunk in enumerate(chunks, start=1)
    ]
    if content:
        content.append(citation_instruction_content())

    _LOGGER.info("search complete correlation_id=%s result_count=%d", cid, len(chunks))
    return CallToolResult(content=cast(list[ContentBlock], content))
