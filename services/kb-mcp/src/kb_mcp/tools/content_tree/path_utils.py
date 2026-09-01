"""Display-path helpers for content_tree rows."""

from collections.abc import Sequence
from pathlib import PurePath

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
