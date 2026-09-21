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
from unique_sdk import UniqueError
from unique_toolkit.experimental.components.internal_search import (
    InternalSearchPostProcessor,
    KnowledgeBaseInternalSearchConfig,
    KnowledgeBaseInternalSearchService,
)

from kb_mcp.common.correlation import correlation_id
from kb_mcp.common.metadata_filter import (
    merge_request_metadata_filter,
    try_parse_llm_metadata_filter,
)
from kb_mcp.common.references import (
    METADATA_FILTER_EMPTY_RETRY_HINT,
    SEARCH_SYSTEM_PROMPT,
    TOOL_DESCRIPTION_CITATION_GUIDANCE,
    UNIQUE_AI_TOOL_FORMAT_INFORMATION,
    MetadataFilterArgument,
    chunk_to_text_content,
    citation_instruction_content,
    is_unique_ai_client,
)
from kb_mcp.settings import get_settings
from kb_mcp.tools.search.config import SearchToolConfig
from kb_mcp.tools.search.scope_resolver import resolve_scope_ids

_LOGGER = logging.getLogger(__name__)


def _effective_service_config(
    config: KnowledgeBaseInternalSearchConfig,
    *,
    limit: int | None,
    score_threshold: float | None,
) -> KnowledgeBaseInternalSearchConfig:
    """Non-mutating override of filtering.limit/score_threshold."""
    overrides = {
        k: v
        for k, v in {"limit": limit, "score_threshold": score_threshold}.items()
        if v is not None
    }
    if not overrides:
        return config
    return config.model_copy(
        update={"filtering": config.filtering.model_copy(update=overrides)}
    )


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
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
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
    metadata_filter: MetadataFilterArgument = None,
    limit: Annotated[
        int | None,
        Field(
            gt=0,
            description=(
                "Maximum chunks to return before post-processing. Ships "
                "with a conservative default (200) this tenant's admin may "
                "have changed — omit to use whatever's actually configured, "
                "and only pass a value if you specifically need to raise or "
                "lower it."
            ),
        ),
    ] = None,
    score_threshold: Annotated[
        float | None,
        Field(
            ge=0.0,
            le=1.0,
            multiple_of=0.01,
            description=(
                "Minimum relevance score in [0.0, 1.0], up to 2 decimal "
                "places; higher is stricter. Ships with a default of 0.0 "
                "this tenant's admin may have changed — omit to use "
                "whatever's actually configured."
            ),
        ),
    ] = None,
    config: SearchToolConfig = Depends(get_tool_config(SearchToolConfig)),
) -> ToolResult:
    """Search the knowledge base using ``SearchToolConfig`` from the config meta key."""
    kb_settings = get_settings()
    cid: str | None = None
    try:
        parsed_llm_filter, parse_error = try_parse_llm_metadata_filter(metadata_filter)
        if parse_error is not None:
            return parse_error

        # In-body (not Depends) so identity-refusal ValueError surfaces as a tool error.
        settings = await get_unique_settings_async()
        cid = correlation_id(
            settings.authcontext.get_confidential_user_id(),
            settings.authcontext.get_confidential_company_id(),
        )
        _LOGGER.info("search start correlation_id=%s", cid)

        service_config = _effective_service_config(
            config.service_config, limit=limit, score_threshold=score_threshold
        )
        service = KnowledgeBaseInternalSearchService.from_config(
            service_config
        ).bind_settings(settings)
        service.state.search_queries = [search_string]
        if folder_ids or parsed_llm_filter is not None:
            # Override skips toolkit folding of deprecated config.scope_ids.
            scope_ids = config.service_config.scope_ids
            service.state.metadata_filter_override = (  # pyright: ignore[reportAttributeAccessIssue]
                merge_request_metadata_filter(
                    admin_metadata_filter=config.service_config.metadata_filter,
                    folder_ids=folder_ids,
                    include_subfolders=include_subfolders,
                    llm_metadata_filter=parsed_llm_filter,
                    admin_scope_ids=scope_ids if isinstance(scope_ids, list) else None,
                )
            )

        result = await service.run()

        post_processor = InternalSearchPostProcessor.from_settings(
            settings, config=config.post_processing
        )
        chunks = await post_processor.process(result)
    except Exception as exc:
        # UniqueError.__str__ can collapse to "<Unknown code>: <No message>".
        # No json_body here — it can echo the caller's query/filter values.
        sdk_detail = (
            f" http_status={exc.http_status} code={exc.code} "
            f"request_id={exc.request_id}"
            if isinstance(exc, UniqueError)
            else ""
        )
        _LOGGER.exception(
            "search error correlation_id=%s error_type=%s%s",
            cid,
            type(exc).__name__,
            sdk_detail,
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
    elif parsed_llm_filter is not None:
        content = [TextContent(type="text", text=METADATA_FILTER_EMPTY_RETRY_HINT)]

    _LOGGER.info("search complete correlation_id=%s result_count=%d", cid, len(chunks))
    return ToolResult(content=content)
