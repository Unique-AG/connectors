"""HTML→Markdown gist conversion: convert, squeeze markdownify's own conversion artifacts, and
optionally truncate at a word boundary to a caller-supplied budget.

A gist is a prefix, not a summary: it keeps whatever the body starts with, which may be a
table rather than the discussion. See `extract_gist_from_html` for the library choice this
rests on. Omit `max_chars` and the body is not truncated. A conversion that raises returns
the original HTML, under the same `max_chars` cap, so one bad body cannot fail the tool call.
"""

import logging
import re
from typing import ClassVar

from bs4 import BeautifulSoup, Tag
from markdownify import markdownify
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

# Matches a Markdown pipe-table separator cell: `---`, `:---`, `---:`, or `:---:`.
_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")

# markdownify recurses ~2 frames per tag and overflows near 500 nested tags; 200 leaves headroom.
_MAX_TAG_DEPTH = 200

# Any run of whitespace, used to find the last word boundary inside a truncation window.
_WHITESPACE_RE = re.compile(r"\s")


class Gist(BaseModel):
    """A squeezed, word-boundary-truncated Markdown rendering of an HTML activity body.

    `full_length` is the length of the converted-and-squeezed Markdown *before* truncation,
    always populated (equal to `len(text)` when `truncated` is False) so a caller can decide,
    without recomputing anything, whether "more" exists to drill into.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    text: str
    truncated: bool
    full_length: int


def extract_gist_from_html(html: str, *, max_chars: int | None = None) -> Gist:
    """Convert `html` to a squeezed Markdown gist.

    Pass `max_chars` only for a prefix: a timeline page, so a page of gists fits in context,
    or a search row's `short_description`. The cut lands on a word boundary. Omit it for a
    full body — `description` and `get_activity_detail` — and nothing is truncated.

    Conversion is `markdownify` (see module docstring): it renders tables as Markdown pipe
    rows instead of flattening them to a run-on line, which is what keeps a meeting note's
    firm/person attendee pairs from being scrambled together. A body nested deeper than
    markdownify can walk is flattened at that depth and converted again. Squeezing removes
    two of markdownify's own artifacts — the synthetic blank header row it invents for a
    `<th>`-less `<table>`, and runs of blank lines — before truncation ever sees the text.

    Any failure returns the raw `html` instead, so one bad body cannot fail the tool call.
    The two modes still hold: with `max_chars` it is hard-cut to `max_chars` (a list row's
    budget binds whatever the text is, even if the cut lands inside a tag) and marked
    truncated; without it the whole body comes back.
    """
    try:
        return _gist(_html_to_markdown(html), max_chars=max_chars)
    except Exception:
        logger.warning(
            "activity_history.gist.conversion_failed",
            extra={"html_chars": len(html)},
            exc_info=True,
        )
        if max_chars is None or len(html) <= max_chars:
            return Gist(text=html, truncated=False, full_length=len(html))
        return Gist(text=html[:max_chars], truncated=True, full_length=len(html))


def _gist(markdown: str, *, max_chars: int | None) -> Gist:
    squeezed = _squeeze(markdown)
    full_length = len(squeezed)
    if max_chars is None or full_length <= max_chars:
        return Gist(text=squeezed, truncated=False, full_length=full_length)
    truncated_text = _truncate_at_word_boundary(squeezed, max_chars)
    logger.debug(
        "activity_history.gist.truncated",
        extra={"full_length": full_length, "max_chars": max_chars, "kept": len(truncated_text)},
    )
    return Gist(text=truncated_text, truncated=True, full_length=full_length)


def _html_to_markdown(html: str) -> str:
    """Convert `html` to Markdown, flattening over-deep subtrees instead of overflowing."""
    try:
        return markdownify(html)
    except RecursionError:
        capped = _cap_nesting(html, max_depth=_MAX_TAG_DEPTH)
        logger.warning(
            "activity_history.gist.nesting_capped",
            extra={"html_chars": len(html), "max_depth": _MAX_TAG_DEPTH},
        )
        return markdownify(capped)


def _cap_nesting(html: str, *, max_depth: int) -> str:
    """Replace every tag nested deeper than `max_depth` with its own text.

    Only the over-deep subtree is flattened, so a table sitting higher in the body still
    converts to Markdown pipe rows.
    """
    soup = BeautifulSoup(html, "html.parser")
    too_deep: list[Tag] = []
    seen: set[int] = set()
    stack: list[tuple[Tag, int]] = [(soup, 0)]
    while stack:
        node, depth = stack.pop()
        node_id = id(node)
        if node_id in seen:
            continue
        seen.add(node_id)
        if node is not soup and depth > max_depth:
            too_deep.append(node)
            continue
        for child in tuple(node.contents):
            if isinstance(child, Tag):
                stack.append((child, depth + 1))
    for node in too_deep:
        node.replace_with(node.get_text("\n", strip=True))
    return str(soup)


def _squeeze(markdown: str) -> str:
    """Drop markdownify's synthetic empty pipe-header rows, then collapse blank-line runs."""
    without_synthetic_headers = _drop_synthetic_table_headers(markdown)
    return _collapse_blank_lines(without_synthetic_headers).strip()


def _drop_synthetic_table_headers(markdown: str) -> str:
    """Remove markdownify's blank `|  |  |  |` header row plus its `| --- | --- |` separator.

    markdownify emits that pair only as the first two lines of a `<th>`-less table's block of
    contiguous pipe-table lines, so only those two lines are checked — identical rows deeper in
    a table are real content and are kept.
    """
    lines = markdown.split("\n")
    kept: list[str] = []
    index = 0
    while index < len(lines):
        block_end = index
        while block_end < len(lines) and _pipe_cells(lines[block_end]) is not None:
            block_end += 1
        if block_end == index:
            kept.append(lines[index])
            index += 1
            continue
        block = lines[index:block_end]
        if len(block) >= 2 and _is_blank_pipe_row(block[0]) and _is_separator_row(block[1]):
            block = block[2:]
        kept.extend(block)
        index = block_end
    return "\n".join(kept)


def _collapse_blank_lines(markdown: str) -> str:
    """Collapse any run of consecutive blank (or whitespace-only) lines down to one."""
    collapsed: list[str] = []
    previous_was_blank = False
    for line in markdown.split("\n"):
        is_blank = line.strip() == ""
        if is_blank and previous_was_blank:
            continue
        collapsed.append("" if is_blank else line)
        previous_was_blank = is_blank
    return "\n".join(collapsed)


def _pipe_cells(line: str) -> list[str] | None:
    """The cell contents of a Markdown pipe-table row, or `None` if `line` is not one.

    A pipe-table row starts and ends with `|` (markdownify always emits both) with at least
    one cell in between.
    """
    stripped = line.strip()
    if len(stripped) < 2 or not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    return stripped[1:-1].split("|")


def _is_blank_pipe_row(line: str) -> bool:
    cells = _pipe_cells(line)
    return cells is not None and all(cell.strip() == "" for cell in cells)


def _is_separator_row(line: str) -> bool:
    cells = _pipe_cells(line)
    return cells is not None and all(_SEPARATOR_CELL_RE.match(cell.strip()) for cell in cells)


def _truncate_at_word_boundary(text: str, max_chars: int) -> str:
    """Cut `text` to at most `max_chars`, landing on a real word boundary.

    Falls back to a hard cut only when the leading `max_chars` window has no whitespace at all
    (one token longer than the whole budget) — there is no word boundary to land on there.
    """
    window = text[:max_chars]
    boundaries = list(_WHITESPACE_RE.finditer(window))
    if not boundaries:
        return window
    return window[: boundaries[-1].start()].rstrip()
