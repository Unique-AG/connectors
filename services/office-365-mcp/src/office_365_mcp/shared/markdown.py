from typing import cast

from markdown_it import MarkdownIt

_MARKDOWN = (
    MarkdownIt("commonmark", {"html": False, "breaks": True})
    .enable(["strikethrough", "table"])
    .disable("image")
)


def markdown_to_html(text: str) -> str:
    return cast("str", _MARKDOWN.render(text)).strip()
