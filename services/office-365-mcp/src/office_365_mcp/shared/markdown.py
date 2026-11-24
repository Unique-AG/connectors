from html.parser import HTMLParser
from typing import Literal, cast, override

from markdown_it import MarkdownIt

type BodyFormat = Literal["markdown", "html"]

BODY_FORMAT_FIELD: str = (
    "The format of `body`: `markdown` (the default) or `html`. This tool sends HTML to Microsoft "
    + "as it is. Use `html` when the user asks for styled text, such as fonts, colours or a table "
    + "layout. Use inline `style` attributes, tables for layout and common fonts such as Arial or "
    + "Calibri, because desktop Outlook ignores some CSS."
)

_MARKDOWN = (
    MarkdownIt("commonmark", {"html": False, "breaks": True})
    .enable(["strikethrough", "table"])
    .disable("image")
)


def markdown_to_html(text: str) -> str:
    return cast("str", _MARKDOWN.render(text)).strip()


def body_to_html(text: str, body_format: BodyFormat) -> str:
    return text if body_format == "html" else markdown_to_html(text)


def link_targets(text: str) -> tuple[str, ...]:
    destinations = (
        child.attrGet("href")
        for token in _MARKDOWN.parse(text)
        for child in token.children or ()
        if child.type == "link_open"
    )
    return tuple(dict.fromkeys(url for url in destinations if isinstance(url, str)))


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.targets: list[str] = []

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("a", "area") or tag.startswith("v:"):
            self.targets.extend(value for name, value in attrs if name == "href" and value)

    @override
    def handle_comment(self, data: str) -> None:
        opening, separator, conditional = data.partition("]>")
        if separator and opening.lstrip().startswith("[if"):
            self.targets.extend(html_link_targets(conditional.removesuffix("<![endif]")))


def html_link_targets(html: str) -> tuple[str, ...]:
    collector = _LinkCollector()
    collector.feed(html)
    collector.close()
    return tuple(dict.fromkeys(collector.targets))


def links_in_body(body_html: str) -> str:
    targets = html_link_targets(body_html)
    return f" It links to {', '.join(repr(target) for target in targets)}." if targets else ""
