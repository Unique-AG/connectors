"""The only forms a tool can show. One required field, no default: an empty accept picks nothing."""

from collections.abc import Sequence

from mcp_elicitation.results import Option

type Form = dict[str, object]

CONFIRM = "confirm"
CANCEL = "cancel"
ANSWER_FIELD = "answer"
CHOICE_FIELD = "choice"
CHOICES_FIELD = "choices"


def confirm_form(*, agree: str, decline: str) -> Form:
    return _form(
        ANSWER_FIELD,
        {
            "type": "string",
            "title": "Answer",
            "oneOf": [{"const": CONFIRM, "title": agree}, {"const": CANCEL, "title": decline}],
        },
    )


def choose_one_form(options: Sequence[Option]) -> Form:
    return _form(CHOICE_FIELD, {"type": "string", "title": "Choice", "oneOf": _titled(options)})


def choose_many_form(options: Sequence[Option], *, min_items: int, max_items: int | None) -> Form:
    field: dict[str, object] = {
        "type": "array",
        "title": "Choices",
        "minItems": min_items,
        "items": {"anyOf": _titled(options)},
    }
    if max_items is not None:
        field["maxItems"] = max_items
    return _form(CHOICES_FIELD, field)


def _titled(options: Sequence[Option]) -> list[dict[str, str]]:
    return [{"const": option.ref, "title": option.label} for option in options]


def _form(name: str, field: dict[str, object]) -> Form:
    return {"type": "object", "properties": {name: field}, "required": [name]}
