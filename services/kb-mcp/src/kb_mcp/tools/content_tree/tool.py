"""Knowledge Base content-tree tool — browse, list, and fuzzy-search visible files.

- CONFIG (admin, per company): ContentTreeToolConfig
- ENV (process-wide): KB_SEARCH_CONTENT_TREE_CACHE_TTL_SECONDS / _MAX_ENTRIES
- STATE (LLM, per call): mode required, rest optional per mode
"""

import logging
from typing import Annotated, Literal

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field
from unique_mcp import (
    ConfigSchemaMeta,
    ContextRequirements,
    MetaKeys,
    get_tool_config,
    get_unique_settings_async,
    merge_tool_meta,
)
from unique_toolkit.content.schemas import ContentInfo
from unique_toolkit.experimental.components.content_tree import ContentTree
from unique_toolkit.experimental.resources.feature_flags._ttl_cache import (
    AsyncTTLCache,
)

from kb_mcp.correlation import correlation_id
from kb_mcp.references import file_reference_url, markdown_citation_link
from kb_mcp.settings import Settings, get_settings
from kb_mcp.tools.content_tree.config import (
    DEFAULT_METADATA_FILTER_STATEMENT,
    ContentTreeToolConfig,
    MatchTarget,
)
from kb_mcp.tools.content_tree.path_utils import (
    display_path,
    display_path_segments,
    normalize_path_segment,
)

_LOGGER = logging.getLogger(__name__)

# Keeps ContentTree instances alive across calls, keyed by (company_id,
# user_id). Single-process only.
_tree_cache: AsyncTTLCache | None = None


def _file_link(
    content_info: ContentInfo,
    segments: list[str],
    frontend_base_url: str | None,
) -> str:
    """Render a file row as a markdown citation (sentinel/brackets stripped)."""
    display = display_path(segments)
    url = file_reference_url(
        content_info.id,
        metadata=content_info.metadata,
        owner_id=content_info.owner_id,
        frontend_base_url=frontend_base_url,
    )
    return markdown_citation_link(display, url)


def _get_tree_cache(settings: Settings) -> AsyncTTLCache:
    global _tree_cache
    if _tree_cache is None:
        _tree_cache = AsyncTTLCache(
            maxsize=settings.content_tree_cache_max_entries,
            ttl_ms=settings.content_tree_cache_ttl_seconds * 1000,
        )
    return _tree_cache


_META = merge_tool_meta(
    {
        "unique.app/icon": "folder-tree",
        "unique.app/system-prompt": (
            "Choose this tool to browse or locate files/folders in the "
            "knowledge base before reading one with the read_file tool."
        ),
    },
    ContextRequirements(
        required=[MetaKeys.USER_ID, MetaKeys.COMPANY_ID],
    ),
    ConfigSchemaMeta(ContentTreeToolConfig),
)


@tool(
    name="content_tree",
    meta=_META,
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def content_tree(
    mode: Annotated[
        Literal["tree", "list", "search"],
        Field(
            description=(
                "Which view to return. 'tree' for an overview, 'list' for a "
                "flat file listing (optionally scoped to folder_path), "
                "'search' for fuzzy filename lookup (requires `query`)."
            )
        ),
    ],
    max_depth: Annotated[
        int | None,
        Field(description="Maximum folder depth to render (1 = top-level only)."),
    ] = None,
    folder_path: Annotated[
        str | None,
        Field(
            description=(
                "Restrict the listing to files under this path, e.g. 'Contracts/2024'."
            )
        ),
    ] = None,
    query: Annotated[
        str | None,
        Field(description="Fuzzy text to match against file names and/or paths."),
    ] = None,
    limit: Annotated[
        int | None,
        Field(description="Maximum number of files/matches to return."),
    ] = None,
    min_score: Annotated[
        float | None,
        Field(
            description=(
                "Minimum fuzzy-match score in [0.0, 1.0]; higher is stricter. "
                "Leave unset unless you have a specific reason to change it."
            )
        ),
    ] = None,
    match_on: Annotated[
        MatchTarget | None,
        Field(
            description=(
                "Score against the file name ('key'), the full folder path "
                "('path'), or both ('both')."
            )
        ),
    ] = None,
    case_sensitive: Annotated[
        bool | None,
        Field(description="Whether fuzzy matching is case-sensitive."),
    ] = None,
    refresh: Annotated[
        bool,
        Field(
            description=(
                "If true, drop this caller's cached tree and refetch from the "
                "backend (~20s). Use when the user reports added/deleted/"
                "changed files and needs a fresh listing."
            )
        ),
    ] = False,
    config: ContentTreeToolConfig = Depends(get_tool_config(ContentTreeToolConfig)),
) -> CallToolResult:
    """Browse the knowledge base's visible file/folder structure. Pick a
    `mode`; only that mode's args below apply, rest ignored. '*' = required.
    - mode='tree': max_depth — first orientation view of folders/files.
    - mode='list': folder_path, limit — flat listing; each result's
    content_id is needed for a later read_file call.
    - mode='search': query*, limit, min_score, match_on, case_sensitive —
    fuzzy filename/path lookup when you know roughly what it's called but
    not where.
    'list' and 'search' rows start with a markdown link that opens the file
    in the Unique knowledge base — paste it as-is when referring the user to
    a file; use the content_id for read_file calls.
    Listings are cached per user (~30 min); repeat calls are fast. When the
    user says they added, deleted, or changed files and needs a fresh tree,
    call with refresh=true (expect a slower ~20s refetch).
    """
    kb_settings = get_settings()
    cid: str | None = None
    try:
        if mode == "search" and not query:
            return CallToolResult(
                isError=True,
                content=[
                    TextContent(
                        type="text",
                        text="query is required when mode='search'",
                    )
                ],
            )

        # In-body (not Depends) so identity-refusal ValueError surfaces as a tool error.
        settings = await get_unique_settings_async()
        company_id = settings.authcontext.get_confidential_company_id()
        user_id = settings.authcontext.get_confidential_user_id()
        cid = correlation_id(user_id, company_id)
        _LOGGER.info("content_tree start correlation_id=%s mode=%s", cid, mode)

        cache = _get_tree_cache(kb_settings)

        async def _construct() -> ContentTree:
            return ContentTree(company_id=company_id, user_id=user_id)

        # SecretStr fields so cache/exception reprs stay masked.
        cache_key = (settings.authcontext.company_id, settings.authcontext.user_id)
        tree_svc, _ = await cache.get_or_fetch(cache_key, _construct)

        if refresh:
            tree_svc.invalidate_cache()

        metadata_filter = (
            config.metadata_filter.to_dict()
            if config.metadata_filter is not None
            else DEFAULT_METADATA_FILTER_STATEMENT.to_dict()
        )

        if mode == "tree":
            text = await tree_svc.render_visible_tree_async(
                max_depth=max_depth,
                metadata_filter=metadata_filter,
                max_concurrent_scope_lookups=config.max_concurrent_scope_lookups,
            )
            _LOGGER.info("content_tree complete correlation_id=%s mode=%s", cid, mode)
            return CallToolResult(content=[TextContent(type="text", text=text)])

        if mode == "list":
            rows = await tree_svc.resolve_visible_file_paths_async(
                metadata_filter=metadata_filter,
                max_concurrent_scope_lookups=config.max_concurrent_scope_lookups,
            )
            if folder_path:
                # Match against display paths (brackets stripped, sentinel dropped)
                # so filters like "SM/AlpenSys" work when segments are ["[SM]", ...].
                prefix = tuple(
                    normalize_path_segment(p) for p in folder_path.strip("/").split("/")
                )
                rows = [
                    (content_info, segments)
                    for content_info, segments in rows
                    if tuple(display_path_segments(segments)[: len(prefix)]) == prefix
                ]
            effective_limit = limit if limit is not None else config.default_limit
            rows = rows[:effective_limit]
            frontend_base_url = kb_settings.frontend_base_url_str()
            lines = [
                f"{_file_link(content_info, segments, frontend_base_url)} "
                f"(content_id={content_info.id})"
                for content_info, segments in rows
            ]
            text = "\n".join(lines) if lines else "No visible files match."
            _LOGGER.info(
                "content_tree complete correlation_id=%s mode=%s result_count=%d",
                cid,
                mode,
                len(rows),
            )
            return CallToolResult(content=[TextContent(type="text", text=text)])

        assert query is not None and mode == "search"
        matches = await tree_svc.search_visible_files_fuzzy_async(
            query,
            limit=limit if limit is not None else config.default_limit,
            min_score=min_score if min_score is not None else config.default_min_score,
            match_on=match_on if match_on is not None else config.default_match_on,
            case_sensitive=(
                case_sensitive
                if case_sensitive is not None
                else config.default_case_sensitive
            ),
            metadata_filter=metadata_filter,
            max_concurrent_scope_lookups=config.max_concurrent_scope_lookups,
        )
        frontend_base_url = kb_settings.frontend_base_url_str()
        lines = [
            f"{_file_link(m.content_info, m.path_segments, frontend_base_url)} "
            f"(score={m.score:.2f}, content_id={m.content_info.id})"
            for m in matches
        ]
        text = "\n".join(lines) if lines else "No matching files found."
        _LOGGER.info(
            "content_tree complete correlation_id=%s mode=%s result_count=%d",
            cid,
            mode,
            len(matches),
        )
        return CallToolResult(content=[TextContent(type="text", text=text)])
    except Exception as exc:
        _LOGGER.exception(
            "content_tree error correlation_id=%s mode=%s error_type=%s",
            cid,
            mode,
            type(exc).__name__,
        )
        return CallToolResult(
            isError=True, content=[TextContent(type="text", text=str(exc))]
        )
