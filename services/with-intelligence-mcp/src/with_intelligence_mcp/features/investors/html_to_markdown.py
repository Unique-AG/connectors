from markdownify import markdownify


def html_to_markdown(html: str | None) -> str | None:
    if html is None:
        return None
    converted = markdownify(html, strip=["a"]).replace(" ", " ").strip()
    return converted or None
