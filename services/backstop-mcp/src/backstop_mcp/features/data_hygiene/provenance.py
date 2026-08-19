"""Extract plain `as_of` provenance from Backstop resource attributes."""

from collections.abc import Mapping
from typing import cast

from backstop_mcp.features.data_hygiene.api_responses import ProvenanceAttributes
from backstop_mcp.features.data_hygiene.responses import AsOfResponse

# Where an instance nests the actor object rather than sending a bare string.
_ACTOR_NAME_KEYS = ("name", "displayName", "display_name", "id")


def extract_as_of(attributes: ProvenanceAttributes | None) -> AsOfResponse | None:
    """Build provenance from `modified_timestamp` / `modified_by` when either is present.

    Returns `None` when both are missing so callers can omit an empty envelope rather than
    echo `{null, null}`. No verdict is attached — age is left for the user to interpret.
    """
    if attributes is None:
        return None
    modified_by = _modified_by(attributes.modified_by)
    if attributes.modified_timestamp is None and modified_by is None:
        return None
    return AsOfResponse(
        modified_timestamp=attributes.modified_timestamp,
        modified_by=modified_by,
    )


def _modified_by(value: object) -> str | None:
    """The actor as a name, whether Backstop sent a string or an object.

    `AsOfResponse.modified_by` cleans whatever this returns, so blank strings pulled out of a nested
    actor are absence there rather than a check here.
    """
    if isinstance(value, str):
        return value.strip() or None
    if not isinstance(value, Mapping):
        return None
    actor = cast("Mapping[str, object]", value)
    return next(
        (
            text.strip()
            for key in _ACTOR_NAME_KEYS
            if isinstance(text := actor.get(key), str) and text.strip()
        ),
        None,
    )
