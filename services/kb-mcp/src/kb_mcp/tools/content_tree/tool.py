"""Knowledge Base content-tree tool — browse, list, and fuzzy-search visible files.

- CONFIG (admin, per company): ContentTreeToolConfig
- ENV (process-wide): KB_MCP_CONTENT_TREE_CACHE_TTL_SECONDS / _MAX_ENTRIES
  and KB_MCP_CONTENT_TREE_TIMEOUT_SECONDS / _MAX_TIMEOUT_SECONDS
- STATE (LLM, per call): mode required, rest optional per mode
"""

import logging
from collections.abc import Sequence
from typing import Annotated, Literal

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
from unique_sdk._error import UniqueError
from unique_toolkit.content.schemas import ContentInfo
from unique_toolkit.experimental.components.content_tree import ContentTree, FuzzyMatch
from unique_toolkit.experimental.components.content_tree.schemas import (
    FolderWalkSnapshot,
)

from kb_mcp.correlation import correlation_id
from kb_mcp.references import (
    METADATA_FILTER_EMPTY_RETRY_HINT,
    MetadataFilterArgument,
    file_reference_url,
    markdown_citation_link,
)
from kb_mcp.scoped_walk import ScopedContentTree
from kb_mcp.settings import Settings, get_settings
from kb_mcp.tools.content_tree.cache import get_tree_cache
from kb_mcp.tools.content_tree.config import (
    DEFAULT_METADATA_FILTER_STATEMENT,
    ContentTreeToolConfig,
    MatchTarget,
)
from kb_mcp.tools.content_tree.path_utils import (
    PathLike,
    display_path,
    display_path_segments,
    folder_scope_ids,
    normalize_path_segment,
    path_parts,
    render_tree_with_folder_ids,
)
from kb_mcp.tools.search.metadata_filter import (
    merge_request_metadata_filter,
    try_parse_llm_metadata_filter,
)

_LOGGER = logging.getLogger(__name__)

_INCOMPLETE_NOTICE = (
    "This listing is incomplete. The folder walk is still running in the "
    "background; call content_tree again (same arguments) to get the "
    "complete tree — that follow-up is usually instant from cache.\n\n"
)


def _with_incomplete_notice(complete: bool, body: str) -> str:
    return ("" if complete else _INCOMPLETE_NOTICE) + body


def _with_truncation_notice(body: str, *, shown: int, total: int) -> str:
    """Distinct from the incomplete notice: there is more, but it was not asked for.

    Incomplete means the walk is still running; truncated means it finished and
    the result was capped. Calling again changes nothing — raise `limit` instead.
    """
    if shown >= total:
        return body
    return (
        f"Showing the first {shown} of {total} files. Raise `limit`, narrow "
        "`folder_path`, or set folders_only=true to see the rest.\n\n"
    ) + body


def _with_empty_metadata_filter_hint(
    body: str, *, empty: bool, complete: bool, llm_filter: object
) -> str:
    if empty and complete and llm_filter is not None:
        return f"{body}\n{METADATA_FILTER_EMPTY_RETRY_HINT}"
    return body


def clamped_content_tree_timeout(requested: float | None, settings: Settings) -> float:
    raw = settings.content_tree_timeout_seconds if requested is None else requested
    return min(max(0.0, raw), settings.content_tree_max_timeout_seconds)


def _mode_misuse_error(
    mode: Literal["tree", "list", "search"],
    *,
    query: str | None,
    match_on: MatchTarget | None,
    min_score: float | None,
    case_sensitive: bool | None,
) -> str | None:
    """A param from the wrong mode silently doing nothing gives the caller no
    signal it made a mistake — surface it instead of quietly ignoring it."""
    if mode != "search":
        search_only = {
            "query": query,
            "match_on": match_on,
            "min_score": min_score,
            "case_sensitive": case_sensitive,
        }
        misused = [name for name, value in search_only.items() if value is not None]
        if misused:
            return (
                f"{', '.join(misused)} only apply to mode='search' and are ignored "
                f"under mode='{mode}'. Call content_tree(mode='search', query=...) "
                f"to filter, or drop them to browse with mode='{mode}'."
            )
    return None


async def _resolve_scope_id(
    folder_path: str, *, user_id: str, company_id: str
) -> str | None:
    """Resolve folder_path — a path or a ``scope_xxx`` id — to a scope id to walk from.

    None means "could not resolve, filter the unscoped walk instead". Raises
    ValueError only for a ``scope_xxx`` id that names nothing readable, since
    there is no sensible fallback for an id the caller claims to have.
    """
    # A raw id short-circuits the SDK resolver without any lookup, so it is
    # checked here: otherwise an unreadable folder walks to an empty result and
    # renders as "this folder is empty" rather than as an error.
    if folder_path.startswith("scope_"):
        try:
            await unique_sdk.Folder.get_info_async(
                user_id=user_id, company_id=company_id, scopeId=folder_path
            )
        except (UniqueError, ValueError) as exc:
            raise ValueError(
                f"No folder readable at folder_path={folder_path!r}."
            ) from exc
        return folder_path

    # A path only resolves against real folder names, but callers pass display
    # names: rendering strips "[" and "]", so the folder stored as "[SM]" is
    # shown, and passed back, as "SM". Those paths cannot be resolved, so they
    # fall back to filtering the unscoped walk — slow, but the behaviour callers
    # already have.
    # TODO [proschu2/ean]: better would be to stop stripping brackets in the
    # rendered label, so what the model reads back is resolvable and every
    # folder_path gets the fast path. That changes rendered output, so it is
    # your call rather than mine.
    absolute = "/" + folder_path.strip("/")
    try:
        return await unique_sdk.Folder.resolve_scope_id_from_folder_path_async(
            user_id=user_id, company_id=company_id, folder_path=absolute
        )
    except UniqueError, ValueError:
        _LOGGER.info("folder_path %r did not resolve; filtering instead", folder_path)
        return None


def _filtered_to_path_prefix(
    snapshot: FolderWalkSnapshot, folder_path: str
) -> FolderWalkSnapshot:
    """Fallback for a folder_path that could not be resolved to a scope id.

    Matches display paths (brackets stripped, sentinel dropped) so 'SM/AlpenSys'
    still finds segments stored as '[SM]'.
    """
    prefix = tuple(normalize_path_segment(p) for p in folder_path.strip("/").split("/"))
    return FolderWalkSnapshot(
        files=[
            (content_info, path)
            for content_info, path in snapshot.files
            if tuple(display_path_segments(path)[: len(prefix)]) == prefix
        ],
        folder_paths=[
            path
            for path in snapshot.folder_paths
            if tuple(display_path_segments(path)[: len(prefix)]) == prefix
        ],
        complete=snapshot.complete,
    )


def _substring_matches(
    files: Sequence[tuple[ContentInfo, PathLike]],
    *,
    query: str,
    limit: int,
    min_score: float,
    match_on: MatchTarget,
    case_sensitive: bool,
) -> list[FuzzyMatch]:
    needle = query if case_sensitive else query.lower()
    matches: list[FuzzyMatch] = []
    for content_info, path in files:
        key = content_info.key or ""
        display = display_path(path)
        key_matches = needle in key if case_sensitive else needle in key.lower()
        path_matches = (
            needle in display if case_sensitive else needle in display.lower()
        )
        if match_on == "key":
            matched, matched_on = key_matches, "key"
        elif match_on == "path":
            matched, matched_on = path_matches, "path"
        else:
            matched = key_matches or path_matches
            matched_on = "key" if key_matches else "path"
        if matched and 1.0 >= min_score:
            matches.append(
                FuzzyMatch(
                    content_info=content_info,
                    path_segments=list(path_parts(path)),
                    score=1.0,
                    matched_on=matched_on,
                )
            )
    return matches[:limit]


def _file_link(
    content_info: ContentInfo,
    path: PathLike,
    frontend_base_url: str | None,
) -> str:
    """Render a file row as a markdown citation (sentinel/brackets stripped)."""
    display = display_path(path)
    url = file_reference_url(
        content_info.id,
        metadata=content_info.metadata,
        owner_id=content_info.owner_id,
        frontend_base_url=frontend_base_url,
    )
    return markdown_citation_link(display, url)


_META = merge_tool_meta(
    {
        "unique.app/icon": "folder-tree",
        "unique.app/system-prompt": (
            "Browse the knowledge base's folder/file structure — use this "
            "only when you need to know what files or folders exist, not to "
            "find information inside them (use search for that). Do not "
            'call this first "to see what\'s there" — search directly. '
            "mode='search' is fuzzy filename/path lookup, not content search. "
            "If a listing says it is incomplete, call this tool again; do "
            "not tell the user missing files do not exist."
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
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
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
    folders_only: Annotated[
        bool,
        Field(
            description=(
                "mode='tree' only: omit files, showing just the folder "
                "structure (like `tree -d`)."
            )
        ),
    ] = False,
    folder_path: Annotated[
        str | None,
        Field(
            description=(
                "Restrict the result to this folder and everything under it — "
                "either its path from the knowledge-base root, e.g. "
                "'Contracts/2024', or a `scope_xxx` id copied verbatim from a "
                "`folder_id=` annotation in mode='tree' output. Applies to all "
                "three modes. Scoping is what makes this tool fast on a large "
                "knowledge base, so pass it whenever the request is about one "
                "folder rather than the whole base."
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
    timeout: Annotated[
        float | None,
        Field(
            ge=0,
            description=(
                "Seconds to wait before returning a partial tree; the walk "
                "continues, so a follow-up call usually returns the complete "
                "tree. The server clamps this below the calling client's own "
                "budget."
            ),
        ),
    ] = None,
    metadata_filter: MetadataFilterArgument = None,
    config: ContentTreeToolConfig = Depends(get_tool_config(ContentTreeToolConfig)),
) -> ToolResult:
    """Browse the knowledge base's folder/file structure — use this only when
    you need to know what files or folders exist, not to find information
    inside them (use search for that). Reach for this when: the user names a
    specific folder/file and you need to resolve its path or content_id; the
    user asks what documents/files exist somewhere rather than a substantive
    question about their content ('which documents do we have owned by X',
    'what's in the X folder', 'list files under X') — that's an enumeration
    request (use mode='list' with folder_path, or mode='tree'), not a content
    search; or you're about to call read_file and need the content_id first.
    Pick a mode; only that mode's args below apply, rest ignored. '*' = required.
    - mode='tree': max_depth, folders_only, timeout — first orientation view
    of folders/files. Folder lines carry `(folder_id=scope_xxx)` when known —
    pass that id as search's `folder_ids` to scope a search to that folder.
    A folder shows no id until the walk reaches a file beneath it; if the one
    you need is missing, re-run with a larger max_depth (folders_only=true
    keeps this cheap — it only hides files from the rendered lines, not from
    the walk that discovers ids).
    - mode='list': folder_path, limit, timeout — flat listing; each result's
    content_id is needed for a later read_file call.
    - mode='search': query*, limit, min_score, match_on, case_sensitive,
    timeout — fuzzy filename/path lookup when you know roughly what a file
    is called but not where it is — not for finding files by their content,
    use search for that.
    'list' and 'search' rows start with a markdown link that opens the file
    in the Unique knowledge base — paste it as-is when referring the user to
    a file; use the content_id for read_file calls.
    Listings are cached per user (~10 min); repeat calls are fast. When the
    user says they added, deleted, or changed files and needs a fresh tree,
    call with refresh=true (expect a slower ~20s refetch).
    timeout is seconds to wait before returning a partial tree; the walk
    continues, so a follow-up call usually returns the complete tree.
    """
    kb_settings = get_settings()
    cid: str | None = None
    try:
        if mode == "search" and not query:
            return ToolResult(
                is_error=True,
                content=[
                    TextContent(
                        type="text",
                        text="query is required when mode='search'",
                    )
                ],
            )

        misuse_error = _mode_misuse_error(
            mode,
            query=query,
            match_on=match_on,
            min_score=min_score,
            case_sensitive=case_sensitive,
        )
        if misuse_error is not None:
            return ToolResult(
                is_error=True,
                content=[TextContent(type="text", text=misuse_error)],
            )

        parsed_llm_filter, parse_error = try_parse_llm_metadata_filter(metadata_filter)
        if parse_error is not None:
            return parse_error

        # In-body (not Depends) so identity-refusal ValueError surfaces as a tool error.
        settings = await get_unique_settings_async()
        company_id = settings.authcontext.get_confidential_company_id()
        user_id = settings.authcontext.get_confidential_user_id()
        cid = correlation_id(user_id, company_id)
        _LOGGER.info("content_tree start correlation_id=%s mode=%s", cid, mode)

        # Rooting the walk at the requested folder is the whole speed fix:
        # measured on QA, 24.6s unscoped versus 2.0s for a 6.5k-file subtree.
        # TODO [proschu2/ean]: a rooted walk yields paths relative to the root,
        # so scoping to Contracts renders "2024/a.pdf", not "Contracts/2024/a.pdf"
        # as the filtered walk did. Reads naturally, like ls in a directory, and
        # matches what content_metadata already does — but it is a visible change
        # to list/search output, so say if you would rather re-prefix the root.
        root_scope_id: str | None = None
        if folder_path:
            try:
                root_scope_id = await _resolve_scope_id(
                    folder_path, user_id=user_id, company_id=company_id
                )
            except ValueError as exc:
                return ToolResult(
                    is_error=True,
                    content=[TextContent(type="text", text=str(exc))],
                )

        cache = get_tree_cache(kb_settings)

        async def _construct() -> ContentTree:
            if root_scope_id:
                return ScopedContentTree(
                    company_id=company_id,
                    user_id=user_id,
                    root_scope_ids=(root_scope_id,),
                )
            return ContentTree(company_id=company_id, user_id=user_id)

        # SecretStr fields so cache/exception reprs stay masked. The scope is part
        # of the key: a subtree walk must never be served from the full-tree entry.
        cache_key = (
            settings.authcontext.company_id,
            settings.authcontext.user_id,
            root_scope_id,
        )
        tree_svc, _ = await cache.get_or_fetch(cache_key, _construct)

        if refresh:
            tree_svc.invalidate_cache()

        resolved_metadata_filter = merge_request_metadata_filter(
            admin_metadata_filter=config.metadata_filter
            or DEFAULT_METADATA_FILTER_STATEMENT,
            llm_metadata_filter=parsed_llm_filter,
        )
        assert resolved_metadata_filter is not None
        wait = clamped_content_tree_timeout(timeout, kb_settings)
        # Walk one level past max_depth — otherwise a folder exactly at the
        # cutoff never gets its own contents visited and stays id-less.
        walk_depth = None
        if mode == "tree":
            walk_depth = max_depth if max_depth is None else max_depth + 1

        snapshot = await tree_svc.resolve_visible_file_paths_via_folders_async(
            metadata_filter=resolved_metadata_filter,
            max_depth=walk_depth,
            timeout=wait,
            max_concurrent_directory_listings=config.max_concurrent_scope_lookups,
        )

        fallback_filtered = bool(folder_path) and root_scope_id is None
        if fallback_filtered:
            assert folder_path is not None
            snapshot = _filtered_to_path_prefix(snapshot, folder_path)

        if mode == "tree":
            # A silently truncated tree reads as authoritative structure, so the
            # model reports a cut-off folder as nonexistent. Cap it, and say so.
            tree_limit = limit if limit is not None else config.default_tree_limit
            rendered = snapshot
            if not folders_only and len(snapshot.files) > tree_limit:
                rendered = FolderWalkSnapshot(
                    files=snapshot.files[:tree_limit],
                    folder_paths=snapshot.folder_paths,
                    complete=snapshot.complete,
                )
            tree_body = _with_empty_metadata_filter_hint(
                render_tree_with_folder_ids(
                    rendered,
                    # Ids come from the full snapshot, not the truncated one: a
                    # folder whose files all fall past the cap would otherwise
                    # lose the folder_id callers need to scope a follow-up call.
                    folder_scope_ids(snapshot.files),
                    max_depth=max_depth,
                    show_files=not folders_only,
                ),
                empty=not snapshot.files,
                complete=snapshot.complete,
                llm_filter=parsed_llm_filter,
            )
            text = _with_incomplete_notice(
                snapshot.complete,
                _with_truncation_notice(
                    tree_body, shown=len(rendered.files), total=len(snapshot.files)
                ),
            )
            _LOGGER.info("content_tree complete correlation_id=%s mode=%s", cid, mode)
            return ToolResult(content=[TextContent(type="text", text=text)])

        if mode == "list":
            # No post-walk path filtering: folder_path already rooted the walk,
            # so everything in the snapshot is in scope.
            rows = list(snapshot.files)
            effective_limit = limit if limit is not None else config.default_limit
            rows = rows[:effective_limit]
            frontend_base_url = kb_settings.frontend_base_url_str()
            lines = [
                f"{_file_link(content_info, path, frontend_base_url)} "
                f"(content_id={content_info.id})"
                for content_info, path in rows
            ]
            body = _with_empty_metadata_filter_hint(
                "\n".join(lines) if lines else "No visible files match.",
                empty=not lines,
                complete=snapshot.complete,
                llm_filter=parsed_llm_filter,
            )
            text = _with_incomplete_notice(snapshot.complete, body)
            _LOGGER.info(
                "content_tree complete correlation_id=%s mode=%s result_count=%d",
                cid,
                mode,
                len(rows),
            )
            return ToolResult(content=[TextContent(type="text", text=text)])

        assert query is not None and mode == "search"
        effective_limit = limit if limit is not None else config.default_limit
        effective_min_score = (
            min_score if min_score is not None else config.default_min_score
        )
        effective_match_on = (
            match_on if match_on is not None else config.default_match_on
        )
        effective_case_sensitive = (
            case_sensitive
            if case_sensitive is not None
            else config.default_case_sensitive
        )
        if snapshot.complete and not fallback_filtered:
            matches = await tree_svc.search_visible_files_fuzzy_async(
                query,
                limit=effective_limit,
                min_score=effective_min_score,
                match_on=effective_match_on,
                case_sensitive=effective_case_sensitive,
                metadata_filter=resolved_metadata_filter,
                max_concurrent_scope_lookups=config.max_concurrent_scope_lookups,
            )
        else:
            # The service's own fuzzy search re-walks and would ignore a snapshot
            # narrowed by the folder_path fallback, so match over the rows here.
            matches = _substring_matches(
                snapshot.files,
                query=query,
                limit=effective_limit,
                min_score=effective_min_score,
                match_on=effective_match_on,
                case_sensitive=effective_case_sensitive,
            )
        frontend_base_url = kb_settings.frontend_base_url_str()
        lines = [
            f"{_file_link(m.content_info, m.path_segments, frontend_base_url)} "
            f"(score={m.score:.2f}, content_id={m.content_info.id})"
            for m in matches
        ]
        body = _with_empty_metadata_filter_hint(
            "\n".join(lines) if lines else "No matching files found.",
            empty=not lines,
            complete=snapshot.complete,
            llm_filter=parsed_llm_filter,
        )
        text = _with_incomplete_notice(snapshot.complete, body)
        _LOGGER.info(
            "content_tree complete correlation_id=%s mode=%s result_count=%d",
            cid,
            mode,
            len(matches),
        )
        return ToolResult(content=[TextContent(type="text", text=text)])
    except Exception as exc:
        _LOGGER.exception(
            "content_tree error correlation_id=%s mode=%s error_type=%s",
            cid,
            mode,
            type(exc).__name__,
        )
        return ToolResult(
            is_error=True, content=[TextContent(type="text", text=str(exc))]
        )
