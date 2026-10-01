import html as html_entities

from markdownify import markdownify


def html_to_markdown(value: str | None) -> str | None:
    if value is None:
        return None
    converted = markdownify(html_entities.unescape(value), strip=["a"]).replace(" ", " ").strip()
    return converted or None
