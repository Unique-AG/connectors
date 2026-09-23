"""Knowledge Base content-metadata tool — discover metadata fields and values for a search filter.

- CONFIG (admin): ContentMetadataToolConfig
- STATE (LLM): folder_ids or folder_paths scope the walk; fields, counts_only, and limit shape the catalog
"""

import asyncio
import logging
from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Annotated, Any, Self

import unique_sdk
from fastmcp.dependencies import Depends
from fastmcp.tools import ToolResult, tool
from mcp.types import TextContent, ToolAnnotations
from pydantic import (
    BaseModel,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)
from unique_mcp import (
    ConfigSchemaMeta,
    ContextRequirements,
    MetaKeys,
    get_tool_config,
    get_unique_settings_async,
    merge_tool_meta,
)
from unique_toolkit.experimental.components.content_tree import ContentTree

from kb_mcp.common.cached_walk import resolve_filtered_snapshot
from kb_mcp.common.correlation import correlation_id
from kb_mcp.common.metadata_filter import (
    DEFAULT_METADATA_FILTER_STATEMENT,
    merge_request_metadata_filter,
)
from kb_mcp.common.scoped_walk import ScopedContentTree
from kb_mcp.common.tree_cache import get_tree_cache
from kb_mcp.settings import get_settings
from kb_mcp.tools.content_metadata.config import ContentMetadataToolConfig

_LOGGER = logging.getLogger(__name__)

_INCOMPLETE_NOTICE = (
    "This scan is incomplete. The catalog is still being built in the "
    "background; call content_metadata again (same arguments) to get the "
    "complete picture — that follow-up is usually instant from cache."
)


def _missing_fields_notice(missing: Sequence[str]) -> str:
    return (
        f"No values found for requested fields: {list(missing)}. Field names "
        "are case-sensitive; call content_metadata with counts_only=true to "
        "see which fields exist."
    )


_DEFAULT_VALUE_LIMIT = 50

Scalar = str | int | float | bool | None


class ContentMetadataOutput(BaseModel):
    complete: bool
    notice: list[str] | None = None
    metadata: list[dict[str, list[Scalar]]] | None = None
    metadata_counts: list[dict[str, int]] | None = None

    @model_validator(mode="after")
    def one_catalog(self) -> Self:
        assert (self.metadata is None) != (self.metadata_counts is None)
        return self

    @model_validator(mode="after")
    def incomplete_requires_notice(self) -> Self:
        if not self.complete:
            assert self.notice
        return self

    @model_serializer(mode="wrap")
    def _omit_none(self, serializer: SerializerFunctionWrapHandler) -> dict[str, Any]:
        dumped = serializer(self)
        assert isinstance(dumped, dict)
        return {key: value for key, value in dumped.items() if value is not None}


def _notices(
    *,
    complete: bool,
    truncation: Sequence[str],
    missing: Sequence[str],
) -> list[str] | None:
    if not complete:
        return [_INCOMPLETE_NOTICE]
    lines = [*truncation]
    if missing:
        lines.append(_missing_fields_notice(missing))
    return lines or None


def _value_limit(limit: int | None, ceiling: int) -> int:
    requested = _DEFAULT_VALUE_LIMIT if limit is None else limit
    return min(requested, ceiling)


async def _unreadable_folder_ids(
    folder_ids: Sequence[str],
    *,
    user_id: str,
    company_id: str,
    concurrency: int,
) -> list[str]:
    """Folder ids whose listing the caller cannot read. Probed up front because
    unique_toolkit swallows a failed listing, which would render as an empty
    catalog rather than an error."""
    semaphore = asyncio.Semaphore(concurrency)
    unreadable: list[str] = []

    async def _probe(scope_id: str) -> None:
        async with semaphore:
            try:
                await unique_sdk.Folder.get_info_async(
                    user_id=user_id, company_id=company_id, scopeId=scope_id
                )
            except asyncio.CancelledError, TimeoutError:
                raise
            except Exception as exc:  # noqa: BLE001 — nothing may reach the TaskGroup
                # Escaping here would cancel the siblings and collapse the error
                # into an ExceptionGroup. The class separates a bad id from an
                # outage; the message is dropped because it can carry a folder name.
                _LOGGER.info(
                    "folder_id %s not readable (%s)", scope_id, type(exc).__name__
                )
                unreadable.append(scope_id)

    async with asyncio.TaskGroup() as tg:
        for scope_id in folder_ids:
            _ = tg.create_task(_probe(scope_id))
    return [fid for fid in folder_ids if fid in set(unreadable)]


async def _resolve_folder_paths(
    folder_paths: Sequence[str],
    *,
    user_id: str,
    company_id: str,
    concurrency: int,
) -> tuple[list[str], list[str]]:
    """Scope ids for these paths, and the paths that resolved to nothing.

    An unresolved path is returned rather than dropped: dropping it would leave
    the walk unscoped, so asking about one folder would answer for the whole
    knowledge base.
    """
    semaphore = asyncio.Semaphore(concurrency)
    resolved: dict[str, str] = {}
    unresolved: list[str] = []

    async def _resolve(folder_path: str) -> None:
        async with semaphore:
            try:
                scope_id = (
                    await unique_sdk.Folder.resolve_scope_id_from_folder_path_async(
                        user_id=user_id,
                        company_id=company_id,
                        folder_path="/" + folder_path.strip("/"),
                    )
                )
            except asyncio.CancelledError, TimeoutError:
                raise
            except Exception as exc:  # noqa: BLE001 — nothing may reach the TaskGroup
                _LOGGER.info("folder_path did not resolve (%s)", type(exc).__name__)
                unresolved.append(folder_path)
                return
            if scope_id:
                resolved[folder_path] = scope_id
            else:
                unresolved.append(folder_path)

    async with asyncio.TaskGroup() as tg:
        for folder_path in folder_paths:
            _ = tg.create_task(_resolve(folder_path))
    return [resolved[p] for p in folder_paths if p in resolved], unresolved


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
            "itself. On a large knowledge base, call counts_only=true "
            "first to see field sizes, then fields to fetch only the "
            "ones you need. A notice entry 'field: showing N of M "
            "values' means the rest were withheld; calling again with "
            "the same limit returns the same values. Optionally scope it "
            "to one or more folders with folder_ids (same as search's), "
            "or to one or more folders by exact path with folder_paths "
            "if you don't have scope_xxx ids in hand. If the result says "
            "the scan is incomplete, call this tool again; do not tell "
            "the user missing fields/values do not exist."
        ),
    },
    ContextRequirements(
        required=[MetaKeys.USER_ID, MetaKeys.COMPANY_ID],
    ),
    ConfigSchemaMeta(ContentMetadataToolConfig),
)


@tool(
    name="content_metadata",
    output_schema=ContentMetadataOutput.model_json_schema(),
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
    fields: Annotated[
        list[str] | None,
        Field(
            description=(
                "Only return these metadata fields, by exact (case-sensitive) "
                "name as listed by a counts_only=true call. Omit (null) to "
                "return every field; an empty list returns no fields."
            )
        ),
    ] = None,
    counts_only: Annotated[
        bool,
        Field(
            description=(
                "If true, return each field's distinct-value count instead "
                "of its values, under metadata_counts — e.g. "
                '{"complete": true, "metadata_counts": [{"department": 12}]}, '
                "most widely used field first. Use it to see what fields "
                "exist, and how big each value list is, before requesting "
                "values for a few of them with fields. Ignores limit."
            )
        ),
    ] = False,
    limit: Annotated[
        int | None,
        Field(
            ge=1,
            description=(
                "Maximum distinct values to return per field, most common "
                "first. Omit for 50. Clamped to the admin ceiling "
                "max_values_per_field. Ignored when counts_only is true."
            ),
        ),
    ] = None,
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
) -> ContentMetadataOutput | ToolResult:
    """Discover metadata fields and values on the knowledge base's visible
    content (optionally scoped to folder_ids), so a caller can build a
    metadata filter for search. Returns one JSON object with complete, an
    optional notice list, and exactly one catalog: metadata (field name to
    its values) or, with counts_only, metadata_counts (field name to its
    distinct-value count). e.g. {"complete": true, "metadata":
    [{"department": ["Legal", "Finance"]}]}. Once the scan is complete,
    notice names each field whose value list was shortened. Values here
    describe what filtering is *possible*, not a guarantee today's search
    tool accepts an arbitrary metadata filter — check with the user's
    actual search tool before promising a filter will work.
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

        # Resolved up front so the rest of the function treats them as folder
        # ids. The backend's lookup needs an absolute path, so bare ones are
        # normalized rather than making the caller know that.
        effective_folder_ids = folder_ids
        if folder_ids:
            unreadable = await _unreadable_folder_ids(
                folder_ids,
                user_id=user_id,
                company_id=company_id,
                concurrency=config.max_concurrent_scope_lookups,
            )
            if unreadable:
                return ToolResult(
                    is_error=True,
                    content=[
                        TextContent(
                            type="text",
                            text=(
                                f"No folder readable at folder_ids: {unreadable}. "
                                "Pass scope_xxx ids from content_tree(mode='tree') "
                                "output, or retry if the knowledge base is "
                                "temporarily unavailable."
                            ),
                        )
                    ],
                )
        if folder_paths:
            resolved, unresolved = await _resolve_folder_paths(
                folder_paths,
                user_id=user_id,
                company_id=company_id,
                concurrency=config.max_concurrent_scope_lookups,
            )
            if unresolved:
                return ToolResult(
                    is_error=True,
                    content=[
                        TextContent(
                            type="text",
                            text=(
                                f"No folder found at folder_paths: {unresolved}. "
                                "Give each path from the knowledge-base root, e.g. "
                                "'Contracts/2024', or pass folder_ids instead."
                            ),
                        )
                    ],
                )
            effective_folder_ids = resolved

        # include_subfolders=False is max_depth=1 on the same rooted walk:
        # roots enter at depth 0, so nothing below them is visited.
        scoped_root_ids: tuple[str, ...] | None = None
        if effective_folder_ids:
            scoped_root_ids = tuple(sorted(set(effective_folder_ids)))
        use_scoped_walk = scoped_root_ids is not None
        walk_depth = None if include_subfolders else 1

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

        metadata_filter = merge_request_metadata_filter(
            admin_metadata_filter=config.metadata_filter
            or DEFAULT_METADATA_FILTER_STATEMENT,
        )
        wait = kb_settings.clamped_walk_timeout(timeout)
        # All admin here — no LLM filter reaches this tool — so the whole thing
        # rides in the walk and nothing is filtered in memory.
        snapshot = await resolve_filtered_snapshot(
            tree_svc,
            walk_filter=metadata_filter,
            post_filter=None,
            max_depth=walk_depth if use_scoped_walk else None,
            timeout=wait,
            max_concurrent_directory_listings=config.max_concurrent_scope_lookups,
        )

        excluded = set(config.excluded_fields)
        # [] is a request for no fields, not an omission.
        requested = set(fields) if fields is not None else None
        field_file_counts: Counter[str] = Counter()
        field_value_counts: defaultdict[str, Counter[Any]] = defaultdict(Counter)

        for content_info, _path in snapshot.files:
            item_metadata = content_info.metadata or {}
            for meta_field, raw_value in item_metadata.items():
                if meta_field in excluded:
                    continue
                if requested is not None and meta_field not in requested:
                    continue
                values = _flatten_metadata_value(raw_value)
                if not values:
                    continue
                field_file_counts[meta_field] += 1
                for value in values:
                    field_value_counts[meta_field][value] += 1

        ranked_fields = [
            meta_field for meta_field, _file_count in field_file_counts.most_common()
        ]
        # Missing names and withheld counts wait until the scan finishes.
        missing = (
            [f for f in dict.fromkeys(fields or []) if f not in field_file_counts]
            if snapshot.complete
            else []
        )
        page = _value_limit(limit, config.max_values_per_field)
        if counts_only:
            output = ContentMetadataOutput(
                complete=snapshot.complete,
                notice=_notices(
                    complete=snapshot.complete, truncation=[], missing=missing
                ),
                metadata_counts=[
                    {meta_field: len(field_value_counts[meta_field])}
                    for meta_field in ranked_fields
                ],
            )
        else:
            metadata: list[dict[str, list[Scalar]]] = []
            truncation: list[str] = []
            for meta_field in ranked_fields:
                counter = field_value_counts[meta_field]
                shown = [value for value, _count in counter.most_common(page)]
                metadata.append({meta_field: shown})
                if len(shown) < len(counter):
                    truncation.append(
                        f"{meta_field}: showing {len(shown)} of {len(counter)} values."
                    )
            output = ContentMetadataOutput(
                complete=snapshot.complete,
                notice=_notices(
                    complete=snapshot.complete, truncation=truncation, missing=missing
                ),
                metadata=metadata,
            )

        field_count = len(output.metadata_counts or output.metadata or [])
        _LOGGER.info(
            "content_metadata complete correlation_id=%s field_count=%d",
            cid,
            field_count,
        )
        return output
    except Exception as exc:
        _LOGGER.exception(
            "content_metadata error correlation_id=%s error_type=%s",
            cid,
            type(exc).__name__,
        )
        return ToolResult(
            is_error=True, content=[TextContent(type="text", text=str(exc))]
        )
