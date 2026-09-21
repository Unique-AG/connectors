import html
import re

_A_TAG = re.compile(r"<(?:!--.*?--|/?[A-Za-z][^<>]*)>", re.DOTALL)
_A_HIDDEN_ELEMENT = re.compile(r"<(script|style)\b[^<>]*>.*?</\1\s*>", re.DOTALL | re.IGNORECASE)

PREVIEW_CHARACTERS = 120


def cut_for_a_question(text: str) -> str:
    if len(text) <= PREVIEW_CHARACTERS:
        return text
    return f"{text[:PREVIEW_CHARACTERS]}…"


def body_opening(body_html: str) -> str:
    without_hidden = _A_HIDDEN_ELEMENT.sub(" ", body_html)
    without_tags = _A_TAG.sub(" ", without_hidden)
    return cut_for_a_question(" ".join(html.unescape(without_tags).split()))
