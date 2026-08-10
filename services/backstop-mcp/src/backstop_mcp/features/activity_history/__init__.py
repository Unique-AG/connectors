"""HTML-to-gist conversion for meeting notes and other rich-text activity bodies.

The public surface is `to_gist`: convert HTML to Markdown with `markdownify`, squeeze its own
conversion artifacts (synthetic empty-header table rows, blank-line runs), and truncate at a
word boundary to a caller-supplied budget. `Gist` is the result — converted text, whether it
was truncated, and the full pre-truncation length, so a caller can tell whether "more" exists
without recomputing anything.

This is a pure, standalone utility — not yet wired into any tool. The streams/merge/cursor/tool
layer that will call it lives in later `activity_history` modules.
"""

from backstop_mcp.features.activity_history.gist import Gist, to_gist

__all__ = [
    "Gist",
    "to_gist",
]
