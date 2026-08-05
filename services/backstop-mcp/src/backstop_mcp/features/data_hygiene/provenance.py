"""Extract plain `as_of` provenance from Backstop resource attributes."""

from backstop_mcp.coerce import as_clean_str, as_object_dict
from backstop_mcp.features.data_hygiene.types import AsOf


def extract_as_of(attributes: dict[str, object] | None) -> AsOf | None:
    """Build provenance from `modifiedTimestamp` / `modifiedBy` when either is present.

    Returns `None` when both are missing so callers can omit an empty envelope rather than
    echo `{null, null}`. No verdict is attached — age is left for the user to interpret.
    """
    if not attributes:
        return None
    modified_timestamp = as_clean_str(attributes.get("modifiedTimestamp"))
    modified_by = _modified_by(attributes.get("modifiedBy"))
    if modified_timestamp is None and modified_by is None:
        return None
    return AsOf(modified_timestamp=modified_timestamp, modified_by=modified_by)


def _modified_by(value: object) -> str | None:
    text = as_clean_str(value)
    if text is not None:
        return text
    # Some instances nest the actor as `{name}` / `{id}` rather than a bare string.
    nested = as_object_dict(value)
    if nested is None:
        return None
    for key in ("name", "displayName", "display_name", "id"):
        label = as_clean_str(nested.get(key))
        if label is not None:
            return label
    return None
