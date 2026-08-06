"""Display-path helpers for content_tree rows."""

from collections.abc import Sequence

# Toolkit path helpers emit this sentinel when content has no folderIdPath
# (chat uploads, loose files). Strip it from display labels only — do not
# change toolkit emission; other callers may rely on the literal value.
NO_FOLDER_PATH_SENTINEL = "_no_folder_path"


def normalize_path_segment(segment: str) -> str:
    """Strip ``[`` / ``]`` so display labels and folder_path filters stay aligned."""
    return segment.replace("[", "").replace("]", "")


def display_path_segments(segments: Sequence[str]) -> list[str]:
    """Path segments for display and filtering (sentinel dropped, brackets stripped)."""
    return [normalize_path_segment(s) for s in segments if s != NO_FOLDER_PATH_SENTINEL]


def display_path(segments: Sequence[str]) -> str:
    """Join path segments for display labels.

    Drops the orphan-folder sentinel and strips ``[`` / ``]`` so folder names
    like ``[SM]`` cannot break the outer ``[label](url)`` markdown wrapper.
    """
    return "/".join(display_path_segments(segments))
