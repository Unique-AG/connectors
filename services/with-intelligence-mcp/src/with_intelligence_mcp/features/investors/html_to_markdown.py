from markdownify import markdownify


def html_to_markdown(html: str | None) -> str | None:
    """The vendor writes prose fields as HTML; a model reading raw tags is worse off.

    `summary` arrives as `<p>...<em><strong>Plan Name</strong></em>...</p>` with non-breaking
    spaces. Converting keeps the emphasis that marks a related plan's name while dropping the
    markup around it.
    """
    if html is None:
        return None
    converted = markdownify(html, strip=["a"]).replace(" ", " ").strip()
    return converted or None
