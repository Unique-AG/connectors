from pydantic import BaseModel, ValidationError

__all__ = ["validate_or_none"]


def validate_or_none[ModelT: BaseModel](value: object, *, schema: type[ModelT]) -> ModelT | None:
    """`value` read as `schema`, or None when it does not validate.

    For the case where a shape that fails to parse costs its own field and nothing more — an
    unreadable inline `ResourceRef` should not take the record it hangs off down with it. Keep
    `model_validate` wherever the failure *should* propagate; this is not a blanket replacement.

    The `None` return collapses "absent" and "malformed" into one answer, so a caller that needs
    to warn about the second has to check `value` itself. Callers that log the `ValidationError`
    want `except ValidationError` and the exception, not this.
    """
    try:
        return schema.model_validate(value)
    except ValidationError:
        return None
