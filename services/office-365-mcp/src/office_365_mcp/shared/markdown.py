from typing import cast

from markdown_it import MarkdownIt

_MARKDOWN = (
    MarkdownIt("commonmark", {"html": False, "breaks": True})
    .enable(["strikethrough", "table"])
    .disable("image")
)


def markdown_to_html(text: str) -> str:
    return cast("str", _MARKDOWN.render(text)).strip()


def link_targets(text: str) -> tuple[str, ...]:
    destinations = (
        child.attrGet("href")
        for token in _MARKDOWN.parse(text)
        for child in token.children or ()
        if child.type == "link_open"
    )
    return tuple(dict.fromkeys(url for url in destinations if isinstance(url, str)))
