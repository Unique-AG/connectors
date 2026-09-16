"""Knowledge Base content-metadata tool — discover metadata fields/values
that exist on visible content, so a caller can build a metadata filter.

- CONFIG (admin, per company): ContentMetadataToolConfig
- STATE (LLM, per call): folder_ids/folder_paths/include_subfolders scope
  which content counts; the tool always returns the full field/value catalog
  for that scope

Mirrors content_tree's structure and reuses its per-user ContentTree cache
(same walk, same identity/permission handling), since both tools are just
different views over the same visible-file snapshot. Folder scoping reuses
search's folder-scope filter builder — same `scope_xxx` ids, same
admin-filter-never-bypassed semantics.

Exhaustive for now: every known field and every distinct value it has, with
no caps — pagination will be added once scale requires it.
"""

import asyncio
import json
import logging
import os
from collections import Counter, defaultdict
from typing import Annotated, Any

import unique_sdk
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
from unique_toolkit.experimental.components.content_tree import ContentTree

from kb_mcp.correlation import correlation_id
from kb_mcp.scoped_walk import ScopedContentTree
from kb_mcp.settings import get_settings
from kb_mcp.tools.content_metadata.config import ContentMetadataToolConfig
from kb_mcp.tools.content_metadata.metadata_filter import (
    build_folder_scoped_metadata_filter,
)
from kb_mcp.tools.content_tree.cache import get_tree_cache
from kb_mcp.tools.content_tree.config import DEFAULT_METADATA_FILTER_STATEMENT

_LOGGER = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 30.0
_MAX_TIMEOUT_SECONDS = 45.0

_INCOMPLETE_NOTICE = (
    "This scan is incomplete. The catalog is still being built in the "
    "background; call content_metadata again (same arguments) to get the "
    "complete picture — that follow-up is usually instant from cache."
)

# TODO(ean): temporary benchmarking knob — DELETE this flag, this comment,
# and the `not _DEBUG_FORCE_UNSCOPED_WALK` clause below before merging.
# Set KB_MCP_DEBUG_FORCE_UNSCOPED_WALK=1 (and restart the server) to force
# the pre-ScopedContentTree unscoped-walk-then-filter path, for comparing
# against the scoped fast path below.
_DEBUG_FORCE_UNSCOPED_WALK = os.environ.get("KB_MCP_DEBUG_FORCE_UNSCOPED_WALK") == "1"


def _clamped_timeout(requested: float | None) -> float:
    raw = _DEFAULT_TIMEOUT_SECONDS if requested is None else requested
    return min(max(0.0, raw), _MAX_TIMEOUT_SECONDS)


def _flatten_metadata_value(value: Any) -> list[Any]:
    """List-valued metadata (tags) count each element as its own value;
    scalars count as themselves. Nested objects aren't simply filterable
    (no plain equals/contains against a dict), so they're skipped rather
    than catalogued."""
    if isinstance(value, list):
        return [v for v in value if not isinstance(v, (list, dict))]
    if isinstance(value, dict):
        return []
    return [value]


_META = merge_tool_meta(
    {
        "unique.app/icon": "tags",
        "unique.app/system-prompt": (
            "Discover what metadata fields and values exist on the "
            "knowledge base's visible content, so a caller can build a "
            "metadata filter for search — not for searching content "
            "itself. Returns JSON: a list of single-key objects, e.g. "
            '[{"department": ["Legal", "Finance"]}], one per known field, '
            "listing every distinct value found. Optionally scope it to "
            "one or more folders with folder_ids (same as search's), or to "
            "one or more folders by exact path with folder_paths if you "
            "don't have scope_xxx ids in hand. If the result says the scan "
            "is incomplete, call this tool again; do not tell the user "
            "missing fields/values do not exist."
        ),
    },
    ContextRequirements(
        required=[MetaKeys.USER_ID, MetaKeys.COMPANY_ID],
    ),
    ConfigSchemaMeta(ContentMetadataToolConfig),
)


@tool(
    name="content_metadata",
    meta=_META,
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
async def content_metadata(
    folder_ids: Annotated[
        list[str] | None,
        Field(
            description=(
                "Restrict the catalog to these folders. A value is only "
                "ever a `scope_xxx` id copied verbatim from a `folder_id=` "
                "annotation in content_tree(mode='tree') output — never a "
                "folder name, a path, or an id you assembled yourself. No "
                "id in hand means omit this parameter — the full knowledge "
                "base is the default and correct for most requests."
            )
        ),
    ] = None,
    folder_paths: Annotated[
        list[str] | None,
        Field(
            description=(
                "Restrict the catalog to these folders, each given as its "
                "exact path from the knowledge base root (e.g. "
                "'Contracts/2024') — resolved to `scope_xxx` ids "
                "internally, so you don't need one in hand first. Mutually "
                "exclusive with folder_ids; pass whichever you already have."
            )
        ),
    ] = None,
    include_subfolders: Annotated[
        bool,
        Field(
            description=(
                "Ignored unless folder_ids or folder_paths is set. Leave it "
                "true — a folder's own metadata is often carried by files "
                "in its subfolders, not directly inside it."
            )
        ),
    ] = True,
    refresh: Annotated[
        bool,
        Field(
            description=(
                "If true, drop this caller's cached content snapshot and "
                "rescan the backend (~20s). Use when the user reports "
                "added/changed files and needs fresh values."
            )
        ),
    ] = False,
    timeout: Annotated[
        float | None,
        Field(
            ge=0,
            description=(
                "Seconds to wait before returning a partial catalog; the "
                "scan continues, so a follow-up call usually returns the "
                "complete result."
            ),
        ),
    ] = None,
    config: ContentMetadataToolConfig = Depends(
        get_tool_config(ContentMetadataToolConfig)
    ),
) -> ToolResult:
    """Discover metadata fields and values on the knowledge base's visible
    content (optionally scoped to folder_ids), so a caller can build a
    metadata filter for search. Returns JSON: a list of single-key objects
    mapping a field name to every distinct value found, e.g.
    [{"department": ["Legal", "Finance"]}] — one entry per known field.
    Exhaustive: every field and value the scope has, not a sample. Values
    here describe what filtering is *possible*, not a guarantee today's
    search tool accepts an arbitrary metadata filter — check with the
    user's actual search tool before promising a filter will work.
    """
    kb_settings = get_settings()
    cid: str | None = None
    try:
        if folder_ids and folder_paths:
            return ToolResult(
                is_error=True,
                content=[
                    TextContent(
                        type="text",
                        text="Pass either folder_ids or folder_paths, not both.",
                    )
                ],
            )

        # In-body (not Depends) so identity-refusal ValueError surfaces as a tool error.
        settings = await get_unique_settings_async()
        company_id = settings.authcontext.get_confidential_company_id()
        user_id = settings.authcontext.get_confidential_user_id()
        cid = correlation_id(user_id, company_id)
        _LOGGER.info("content_metadata start correlation_id=%s", cid)

        cache = get_tree_cache(kb_settings)

        # folder_paths resolves to scope ids up front so the rest of the
        # function treats them exactly like folder_ids — same fast path,
        # same include_subfolders=False fallback. The backend's folder-path
        # lookup only accepts an absolute path (every real value the SDK's
        # own CLI ever sends starts with "/"), so a bare relative path like
        # "demo" or "Contracts/2024" is normalized rather than requiring the
        # caller to know that convention.
        effective_folder_ids = folder_ids
        if folder_paths:
            resolved_ids = await asyncio.gather(
                *(
                    unique_sdk.Folder.resolve_scope_id_from_folder_path_async(
                        user_id=user_id,
                        company_id=company_id,
                        folder_path="/" + folder_path.strip("/"),
                    )
                    for folder_path in folder_paths
                )
            )
            effective_folder_ids = [rid for rid in resolved_ids if rid] or None

        # Any number of folder ids, with subfolders included, can walk just
        # those folders' subtrees instead of the whole knowledge base (see
        # ScopedContentTree) — only include_subfolders=False's
        # direct-children-only semantics (narrower than what the always-
        # recursive scoped walk can express) falls back to the unscoped walk
        # filtered by folder_ids below, as before.
        scoped_root_ids: tuple[str, ...] | None = None
        if (
            effective_folder_ids
            and include_subfolders
            and not _DEBUG_FORCE_UNSCOPED_WALK  # TODO(ean): delete with the flag above
        ):
            scoped_root_ids = tuple(sorted(set(effective_folder_ids)))
        use_scoped_walk = scoped_root_ids is not None

        async def _construct() -> ContentTree:
            if scoped_root_ids:
                return ScopedContentTree(
                    company_id=company_id,
                    user_id=user_id,
                    root_scope_ids=scoped_root_ids,
                )
            return ContentTree(company_id=company_id, user_id=user_id)

        # SecretStr fields so cache/exception reprs stay masked.
        cache_key = (
            settings.authcontext.company_id,
            settings.authcontext.user_id,
            scoped_root_ids,
        )
        tree_svc, _ = await cache.get_or_fetch(cache_key, _construct)

        if refresh:
            tree_svc.invalidate_cache()

        metadata_filter = build_folder_scoped_metadata_filter(
            None if use_scoped_walk else effective_folder_ids,
            include_subfolders=include_subfolders,
            admin_metadata_filter=config.metadata_filter
            or DEFAULT_METADATA_FILTER_STATEMENT,
        )
        wait = _clamped_timeout(timeout)
        snapshot = await tree_svc.resolve_visible_file_paths_via_folders_async(
            metadata_filter=metadata_filter,
            timeout=wait,
            max_concurrent_directory_listings=config.max_concurrent_scope_lookups,
        )

        excluded = set(config.excluded_fields)
        field_file_counts: Counter[str] = Counter()
        field_value_counts: defaultdict[str, Counter[Any]] = defaultdict(Counter)

        for content_info, _path in snapshot.files:
            item_metadata = content_info.metadata or {}
            for meta_field, raw_value in item_metadata.items():
                if meta_field in excluded:
                    continue
                values = _flatten_metadata_value(raw_value)
                if not values:
                    continue
                field_file_counts[meta_field] += 1
                for value in values:
                    field_value_counts[meta_field][value] += 1

        payload = [
            {
                meta_field: [
                    value
                    for value, _count in field_value_counts[meta_field].most_common()
                ]
            }
            for meta_field, _file_count in field_file_counts.most_common()
        ]

        content: list[TextContent] = [
            TextContent(type="text", text=json.dumps(payload))
        ]
        if not snapshot.complete:
            content.append(TextContent(type="text", text=_INCOMPLETE_NOTICE))

        _LOGGER.info(
            "content_metadata complete correlation_id=%s field_count=%d",
            cid,
            len(payload),
        )
        return ToolResult(content=content)
    except Exception as exc:
        _LOGGER.exception(
            "content_metadata error correlation_id=%s error_type=%s",
            cid,
            type(exc).__name__,
        )
        return ToolResult(
            is_error=True, content=[TextContent(type="text", text=str(exc))]
        )
