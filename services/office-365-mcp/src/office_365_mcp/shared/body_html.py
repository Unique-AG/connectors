from html.parser import HTMLParser
from typing import override

BODY_HTML_FIELD: str = (
    "An HTML fragment, for example `<p>Hi <b>Anna</b>,</p><ul><li>Budget</li></ul>`. This tool "
    + "sends it to Microsoft as it is. It does not convert Markdown or plain text, and a newline "
    + "is not a line break."
)

OUTLOOK_BODY_HTML_FIELD: str = (
    BODY_HTML_FIELD
    + " Use inline `style` attributes, tables for layout and common fonts such as Arial or "
    + "Calibri, because desktop Outlook ignores some CSS."
)

TEAMS_BODY_HTML_FIELD: str = (
    BODY_HTML_FIELD
    + " Teams shows a smaller set of HTML than Outlook, such as bold, italic, links, lists, "
    + "quotes, code and tables. This tool writes the mention markup from `mentions`."
)

ONENOTE_BODY_HTML_FIELD: str = (
    BODY_HTML_FIELD
    + " OneNote shows headings, paragraphs, lists, tables, bold and italic. Microsoft removes "
    + "JavaScript, CSS and forms."
)


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
