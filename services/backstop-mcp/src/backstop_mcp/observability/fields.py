"""Log `extra` fields as OpenTelemetry attribute values."""

from collections.abc import Iterable, Mapping
from typing import cast

from opentelemetry.util.types import AttributeValue
from pydantic import AliasChoices, BaseModel, ValidationError
from pydantic.fields import FieldInfo

_FAILED_FIELDS_SHOWN = 10


def span_attributes(fields: Mapping[str, object]) -> dict[str, AttributeValue]:
    """`None` is dropped; scalars pass through; collections become string tuples; anything else,
    `IdentifiableValue` included, goes through `str()` — which is what conceals it.
    """
    return {key: _attribute_value(value) for key, value in fields.items() if value is not None}


def failed_fields(failures: Iterable[BaseException]) -> list[str]:
    """`path (error type)` for each pydantic error in `failures`, never the input. A path part that
    is not a field of one of our models, such as a list index or a key read from the record, is `*`.
    """
    known = _model_field_names()
    found = {
        f"{_masked_path(error['loc'], known)} ({error['type']})"
        for failure in failures
        if isinstance(failure, ValidationError)
        for error in failure.errors(include_input=False, include_url=False, include_context=False)
    }
    return sorted(found)[:_FAILED_FIELDS_SHOWN]


def _attribute_value(value: object) -> AttributeValue:
    if isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list | tuple | set | frozenset):
        return tuple(str(item) for item in cast("Iterable[object]", value))
    return str(value)


def _masked_path(loc: tuple[int | str, ...], known: frozenset[str]) -> str:
    return ".".join(part if isinstance(part, str) and part in known else "*" for part in loc) or "*"


def _model_field_names() -> frozenset[str]:
    """Walked on every call: models parametrized or defined after import must count too."""
    names: set[str] = set()
    pending: list[type[BaseModel]] = [BaseModel]
    seen: set[type[BaseModel]] = set()
    while pending:
        model = pending.pop()
        if model in seen:
            continue
        seen.add(model)
        pending.extend(model.__subclasses__())
        if model.__module__.startswith("backstop_mcp."):
            for name, field in model.model_fields.items():
                names.add(name)
                names.update(_aliases(field))
    return frozenset(names)


def _aliases(field: FieldInfo) -> set[str]:
    aliases: set[str] = {field.alias} if field.alias else set()
    validation_alias = field.validation_alias
    if isinstance(validation_alias, str):
        aliases.add(validation_alias)
    elif isinstance(validation_alias, AliasChoices):
        aliases.update(choice for choice in validation_alias.choices if isinstance(choice, str))
    return aliases
