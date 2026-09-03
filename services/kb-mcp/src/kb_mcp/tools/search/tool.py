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
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import ToolResult, tool
from mcp.types import TextContent, ToolAnnotations
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
    SEARCH_SYSTEM_PROMPT,
    TOOL_DESCRIPTION_CITATION_GUIDANCE,
    UNIQUE_AI_TOOL_FORMAT_INFORMATION,
    chunk_to_text_content,
    citation_instruction_content,
    is_unique_ai_client,
)
from kb_mcp.settings import get_settings
from kb_mcp.tools.search.config import SearchToolConfig
from kb_mcp.tools.search.metadata_filter import build_folder_scoped_metadata_filter
from kb_mcp.tools.search.scope_resolver import resolve_scope_ids

_LOGGER = logging.getLogger(__name__)

_META = merge_tool_meta(
    {
        "unique.app/icon": "search",
        "unique.app/system-prompt": SEARCH_SYSTEM_PROMPT,
        "unique.app/tool-format-information": UNIQUE_AI_TOOL_FORMAT_INFORMATION,
    },
    ContextRequirements(
        required=[MetaKeys.USER_ID, MetaKeys.COMPANY_ID],
    ),
    ConfigSchemaMeta(SearchToolConfig),
)


@tool(
    name="search",
    # Not the docstring: this reuses SEARCH_SYSTEM_PROMPT + citation
    # guidance, and a literal docstring can't reference module constants.
    description=SEARCH_SYSTEM_PROMPT + " " + TOOL_DESCRIPTION_CITATION_GUIDANCE,
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
    folder_ids: Annotated[
        list[str] | None,
        Field(
            description=(
                "Restrict results to these folders. A value is only ever a "
                "`scope_xxx` id copied verbatim from a `folder_id=` "
                "annotation in content_tree(mode='tree') output — never a "
                "folder name, a path, an id you assembled yourself, or a "
                "`scope_xxx` lifted from a citation/document link in an "
                "earlier result (those are the leaf folder a file happens "
                "to sit in, not the folder the user named). No id in hand "
                "means omit this parameter — an unrestricted search is the "
                "default and correct for most requests. If the folder you "
                "need shows no id, re-run content_tree(mode='tree', "
                "folders_only=true) with a larger max_depth — a folder only "
                "gets an id once the walk has reached a file beneath it."
            )
        ),
    ] = None,
    include_subfolders: Annotated[
        bool,
        Field(
            description=(
                "Ignored unless folder_ids is set. Leave it true — even "
                "'search only in the Legal folder' means Legal plus "
                "everything nested under it, and folders often hold their "
                "files in subfolders rather than directly, so false often "
                "returns nothing. Set it false only when the user's own "
                "words rule out nested content: 'directly in', 'top level "
                "only', 'not the subfolders'. Plain scoping language ('in "
                "X', 'only in X') keeps it true."
            )
        ),
    ] = True,
    config: SearchToolConfig = Depends(get_tool_config(SearchToolConfig)),
) -> ToolResult:
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
        if folder_ids:
            # KnowledgeBaseInternalSearchState narrows this in, but .state is
            # typed via the generic InternalSearchState base at this call site.
            service.state.metadata_filter_override = (  # pyright: ignore[reportAttributeAccessIssue]
                build_folder_scoped_metadata_filter(
                    folder_ids,
                    include_subfolders=include_subfolders,
                    admin_metadata_filter=config.service_config.metadata_filter,
                )
            )

        result = await service.run()

        post_processor = InternalSearchPostProcessor.from_settings(
            settings, config=config.post_processing
        )
        chunks = await post_processor.process(result)
    except Exception as exc:
        _LOGGER.exception(
            "search error correlation_id=%s error_type=%s", cid, type(exc).__name__
        )
        return ToolResult(
            content=[TextContent(type="text", text=str(exc))], is_error=True
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
        content.append(
            citation_instruction_content(is_unique_ai_chat=is_unique_ai_client())
        )

    _LOGGER.info("search complete correlation_id=%s result_count=%d", cid, len(chunks))
    return ToolResult(content=content)
