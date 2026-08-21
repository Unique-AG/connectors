"""HTML→Markdown gist conversion: convert, squeeze markdownify's own conversion artifacts, and
truncate at a word boundary to a caller-supplied budget.

Note what a gist is *not*: the first ~300 chars of a meeting note are usually its attendee
table, so the gist answers "who" far better than "what was discussed" — nothing here tries to
summarize. See `to_gist` for the library choice this rests on.
"""

import logging
import re
from typing import ClassVar

from markdownify import markdownify
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

# Matches a Markdown pipe-table separator cell: `---`, `:---`, `---:`, or `:---:`.
_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")

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


def to_gist(html: str, *, max_chars: int) -> Gist:
    """Convert `html` to a squeezed Markdown gist, truncated at a word boundary to `max_chars`.

    Conversion is `markdownify` (see module docstring): it renders tables as Markdown pipe
    rows instead of flattening them to a run-on line, which is what keeps a meeting note's
    firm/person attendee pairs from being scrambled together. Squeezing removes two of
    markdownify's own artifacts — the synthetic blank header row it invents for a `<th>`-less
    `<table>`, and runs of blank lines — before truncation ever sees the text.
    """
    converted = markdownify(html)
    squeezed = _squeeze(converted)
    full_length = len(squeezed)
    if full_length <= max_chars:
        return Gist(text=squeezed, truncated=False, full_length=full_length)
    truncated_text = _truncate_at_word_boundary(squeezed, max_chars)
    logger.debug(
        "activity_history.gist.truncated",
        extra={"full_length": full_length, "max_chars": max_chars, "kept": len(truncated_text)},
    )
    return Gist(text=truncated_text, truncated=True, full_length=full_length)


def _squeeze(markdown: str) -> str:
    """Drop markdownify's synthetic empty pipe-header rows, then collapse blank-line runs."""
    without_synthetic_headers = _drop_synthetic_table_headers(markdown)
    return _collapse_blank_lines(without_synthetic_headers).strip()


def _drop_synthetic_table_headers(markdown: str) -> str:
    """Remove markdownify's blank `|  |  |  |` header row plus its `| --- | --- |` separator.

    That pair is markdownify's own artifact for a `<table>` with no `<th>` cells (a plain
    layout table using only `<td>`), and it always emits it as the first two lines of the
    table's block of pipe-table lines — never anywhere deeper. So a genuine blank spacer row or
    a row of `-` placeholder cells further down in a real table must not be mistaken for it, and
    a real `<th>` header (whose cells hold actual text) never matches the blank-row shape in the
    first place. Detecting table blocks first (contiguous runs of pipe-table lines, verified
    empirically to be how markdownify delimits adjacent tables) and only inspecting each block's
    first two lines is what tells the synthetic artifact apart from structurally identical rows
    that happen to appear later.
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
