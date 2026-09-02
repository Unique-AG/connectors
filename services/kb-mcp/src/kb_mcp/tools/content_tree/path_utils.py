"""Display-path helpers for content_tree rows."""

from collections.abc import Mapping, Sequence
from pathlib import PurePath

from unique_toolkit.content.schemas import ContentInfo
from unique_toolkit.experimental.components.content_tree.schemas import (
    FolderWalkSnapshot,
    PathTrieNode,
)

from kb_mcp.references import scope_ids_from_folder_id_path

# Toolkit sentinel for content with no folderIdPath. Strip from labels only;
# other callers rely on the literal value.
NO_FOLDER_PATH_SENTINEL = "_no_folder_path"

PathLike = PurePath | Sequence[str]


def path_parts(path: PathLike) -> Sequence[str]:
    if isinstance(path, PurePath):
        return tuple(part for part in path.parts if part != ".")
    return path


def normalize_path_segment(segment: str) -> str:
    """Strip ``[`` / ``]`` so display labels and folder_path filters stay aligned."""
    return segment.replace("[", "").replace("]", "")


def display_path_segments(path: PathLike) -> list[str]:
    """Path segments for display and filtering (sentinel dropped, brackets stripped)."""
    return [
        normalize_path_segment(s)
        for s in path_parts(path)
        if s != NO_FOLDER_PATH_SENTINEL
    ]


def display_path(path: PathLike) -> str:
    """Join path segments for display labels.

    Drops the orphan-folder sentinel and strips ``[`` / ``]`` so folder names
    like ``[SM]`` cannot break the outer ``[label](url)`` markdown wrapper.
    """
    return "/".join(display_path_segments(path))


def folder_scope_ids(
    files: Sequence[tuple[ContentInfo, PathLike]],
) -> dict[tuple[str, ...], str]:
    """Map each visited folder's raw path-segment tuple to its scope id.

    Derived once from every file's ``metadata["folderIdPath"]`` (the full
    root→leaf ancestor chain), zipped against that file's own raw path
    segments — the same segments the tree trie is keyed by, so a folder only
    lacks an entry if it has no file anywhere beneath it (pointless to filter
    to anyway). ``O(files × path depth)``, a single linear pass.
    """
    result: dict[tuple[str, ...], str] = {}
    for content_info, path in files:
        metadata = content_info.metadata
        folder_id_path = metadata.get("folderIdPath") if metadata else None
        if not folder_id_path:
            continue
        scope_ids = scope_ids_from_folder_id_path(folder_id_path)
        dirs = tuple(path_parts(path))[:-1]
        for depth in range(min(len(dirs), len(scope_ids))):
            result.setdefault(dirs[: depth + 1], scope_ids[depth])
    return result


def render_tree_with_folder_ids(
    snapshot: FolderWalkSnapshot,
    folder_ids: Mapping[tuple[str, ...], str],
    *,
    max_depth: int | None = None,
    show_files: bool = True,
) -> str:
    """``FolderWalkSnapshot.render()``, but with ``(folder_id=scope_xxx)``
    appended to each directory line whose id is known.

    Reuses the toolkit's own trie (``snapshot.to_trie()``) and mirrors
    ``PathTrieNode.format_trie_walk``'s box-drawing/sorting/depth-truncation
    exactly — the toolkit's renderer has no per-node annotation hook, so this
    walks the same tree by hand instead of forking its formatting logic.
    """
    lines = ["."] + _format_node(
        snapshot.to_trie(),
        prefix="",
        depth=0,
        max_depth=max_depth,
        show_files=show_files,
        path=(),
        folder_ids=folder_ids,
    )
    return "\n".join(lines)


def _format_node(
    node: PathTrieNode,
    *,
    prefix: str,
    depth: int,
    max_depth: int | None,
    show_files: bool,
    path: tuple[str, ...],
    folder_ids: Mapping[tuple[str, ...], str],
) -> list[str]:
    if max_depth is not None and depth >= max_depth:
        descendants = node.walk_trie_nodes()
        hidden_dirs = len(descendants) - 1
        hidden_files = sum(len(n.files) for n in descendants)
        if hidden_dirs or (show_files and hidden_files):
            summary = (
                f"{hidden_dirs} dirs, {hidden_files} files below"
                if show_files
                else f"{hidden_dirs} dirs below"
            )
            return [f"{prefix}… ({summary})"]
        return []

    dir_items = sorted(node.children.items())
    entries: list[tuple[str, PathTrieNode | None, bool]] = [
        (name, child, True) for name, child in dir_items
    ]
    if show_files:
        entries.extend((name, None, False) for name in sorted(node.files))

    lines: list[str] = []
    for i, (name, child, is_dir) in enumerate(entries):
        is_last = i == len(entries) - 1
        branch = "└── " if is_last else "├── "
        extension = "    " if is_last else "│   "
        child_path = (*path, name) if is_dir else path
        suffix = ""
        if is_dir:
            scope_id = folder_ids.get(child_path)
            if scope_id:
                suffix = f" (folder_id={scope_id})"
        lines.append(f"{prefix}{branch}{name}{suffix}")
        if is_dir and child is not None:
            lines.extend(
                _format_node(
                    child,
                    prefix=prefix + extension,
                    depth=depth + 1,
                    max_depth=max_depth,
                    show_files=show_files,
                    path=child_path,
                    folder_ids=folder_ids,
                )
            )
    return lines
