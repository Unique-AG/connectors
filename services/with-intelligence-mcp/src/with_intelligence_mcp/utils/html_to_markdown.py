from markdownify import markdownify


def html_to_markdown(value: str | None) -> str | None:
    if value is None:
        return None
    converted = markdownify(value, strip=["a"]).replace(" ", " ").strip()
    return converted or None
