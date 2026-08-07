"""Resolving a custom field's allowed (picklist) values.

Getting this right needs the shape the swagger actually describes, which is two hops, not one:

    custom-field-definitions --relationship `lovSet`--> lov-*-sets
                             --relationship `viewableEntries`/`hiddenEntries`--> lov-entries

`?include=lovSet` therefore side-loads the *set*, into the document's top-level `included`
array — never into the definition's `attributes`, and still one hop short of the values
themselves. Reading `attributes.lovSet` alone yields nothing for a field whose options live in a
relationship, which silently breaks write validation for exactly the picklist fields allowed
values exist to enable.

So allowed values are assembled from three sources, in order of reliability:

1. `GET /lov-entries` — the whole instance's entries, fetched once and grouped by `setId`, then
   joined to each definition by its `lovSet` relationship id. One extra paginated call for the
   entire schema, versus one call per picklist definition.
2. The side-loaded `included` set, when it carries entries inline.
3. `attributes.lovSet` / `attributes.selectOptions`, for instances that inline options on the
   definition itself.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Annotated, ClassVar

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
)

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.coerce import as_object_dict, as_object_list
from backstop_mcp.features.custom_fields.types import AllowedValue, LovEntryAttributes

logger = logging.getLogger(__name__)

_CleanStr: TypeAdapter[str] = TypeAdapter(
    Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
)

_LOV_ENTRIES_PATH = "/lov-entries"

_LABEL_KEYS = ("display", "defaultDisplay", "label", "name", "value", "displayName", "display_name")
_ENTRY_COLLECTION_KEYS = ("entries", "lovEntries", "viewableEntries", "options", "values")

_NonEmptyLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _InlineOption(BaseModel):
    """One inlined picklist option object (or a JSON:API resource/attributes wrapper)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: object | None = None
    label: _NonEmptyLabel | None = Field(
        default=None,
        validation_alias=AliasChoices(*_LABEL_KEYS),
    )


def _clean_str(value: object) -> str | None:
    try:
        return _CleanStr.validate_python(value)
    except ValidationError:
        return None


def _first_nonempty_list(payload: dict[str, object]) -> list[object]:
    """First collection among `_ENTRY_COLLECTION_KEYS` that is a non-empty list.

    `AliasChoices` binds the first *present* key, so a null/empty `entries` would block a
    later usable `viewableEntries` — walk the keys ourselves instead.
    """
    for key in _ENTRY_COLLECTION_KEYS:
        if key not in payload:
            continue
        items = as_object_list(payload.get(key))
        if items:
            return items
    return []


def _usable_label(payload: dict[str, object]) -> str | None:
    """First non-blank label among the known keys (skips null/blank earlier aliases)."""
    for key in _LABEL_KEYS:
        if key not in payload:
            continue
        label = _clean_str(payload.get(key))
        if label is not None:
            return label
    return None


def _option_from_raw(option: object) -> AllowedValue | None:
    label = _clean_str(option)
    if label is not None:
        return AllowedValue(id=None, label=label)

    option_dict = as_object_dict(option)
    resource_id: object | None = None
    payload: object = option
    if option_dict is not None:
        resource_id = option_dict.get("id")
        attributes = as_object_dict(option_dict.get("attributes"))
        if attributes is not None:
            # Keep the JSON:API envelope id — attributes alone often omit it.
            payload = attributes

    option_payload = as_object_dict(payload)
    if option_payload is not None:
        label = _usable_label(option_payload)
        option_id = option_payload.get("id")
        if option_id is None:
            option_id = resource_id
        if label is not None:
            return AllowedValue(
                id=str(option_id) if option_id is not None else None,
                label=label,
            )
        if option_id is not None:
            return AllowedValue(id=str(option_id), label=str(option_id))
        return None

    try:
        parsed = _InlineOption.model_validate(payload)
    except ValidationError:
        return None

    if parsed.label is None:
        if parsed.id is None and resource_id is None:
            return None
        fallback_id = parsed.id if parsed.id is not None else resource_id
        return AllowedValue(id=str(fallback_id), label=str(fallback_id))
    option_id = parsed.id if parsed.id is not None else resource_id
    return AllowedValue(
        id=str(option_id) if option_id is not None else None,
        label=parsed.label,
    )


def _dedupe_by_label(values: Iterable[AllowedValue]) -> tuple[AllowedValue, ...]:
    by_label: dict[str, AllowedValue] = {}
    for value in values:
        by_label.setdefault(value.label, value)
    return tuple(by_label.values())


def inline_allowed_values(
    lov_set: object | None, select_options: object | None
) -> tuple[AllowedValue, ...]:
    """Source 3: options inlined on the definition's own attributes."""
    collected: list[AllowedValue] = []

    for option in as_object_list(select_options):
        value = _option_from_raw(option)
        if value is not None:
            collected.append(value)

    lov_dict = as_object_dict(lov_set)
    if lov_dict is None:
        for option in as_object_list(lov_set):
            value = _option_from_raw(option)
            if value is not None:
                collected.append(value)
        return _dedupe_by_label(collected)

    for option in _first_nonempty_list(lov_dict):
        value = _option_from_raw(option)
        if value is not None:
            collected.append(value)

    # A side-loaded set arrives as a JSON:API resource, so the useful fields are one level
    # down under `attributes` (handled inside `_option_from_raw`) or nested under `data`.
    data_list = as_object_list(lov_dict.get("data"))
    if data_list:
        for item in data_list:
            value = _option_from_raw(item)
            if value is not None:
                collected.append(value)
        return _dedupe_by_label(collected)

    data_dict = as_object_dict(lov_dict.get("data"))
    if data_dict is not None:
        value = _option_from_raw(data_dict)
        if value is not None:
            collected.append(value)
    return _dedupe_by_label(collected)


@dataclass(frozen=True)
class LovEntryIndex:
    """LOV entries grouped by the set they belong to, ordered as the Backstop UI shows them."""

    by_set_id: dict[str, tuple[AllowedValue, ...]]

    def allowed_values(self, lov_set_id: str | None) -> tuple[AllowedValue, ...]:
        if lov_set_id is None:
            return ()
        return self.by_set_id.get(lov_set_id, ())

    @property
    def is_empty(self) -> bool:
        return not self.by_set_id


EMPTY_LOV_INDEX = LovEntryIndex(by_set_id={})


def _entry_sort_key(entry: BackstopApiResource[LovEntryAttributes]) -> tuple[int, str]:
    position = entry.attributes.position
    # Entries without a position sort last but stay stable among themselves, by id.
    return (position if position is not None else 1 << 31, entry.id)


def build_lov_entry_index(
    entries: list[BackstopApiResource[LovEntryAttributes]],
) -> LovEntryIndex:
    """Group `lov-entries` by `setId`, keeping only viewable entries in UI order.

    Hidden entries are excluded: they are values a client has switched off, so offering them
    for a write would produce a value the Backstop UI refuses to display.
    """
    grouped: dict[str, list[BackstopApiResource[LovEntryAttributes]]] = {}
    for entry in entries:
        if entry.attributes.viewable is False:
            continue
        set_id = entry.attributes.set_id
        if set_id is None:
            continue
        grouped.setdefault(str(set_id), []).append(entry)

    by_set_id: dict[str, tuple[AllowedValue, ...]] = {}
    for set_id, set_entries in grouped.items():
        values: list[AllowedValue] = []
        for entry in sorted(set_entries, key=_entry_sort_key):
            attributes = entry.attributes
            label = attributes.display or attributes.default_display or attributes.code
            if label is None:
                continue
            values.append(AllowedValue(id=entry.id, label=label))
        deduped = _dedupe_by_label(values)
        if deduped:
            by_set_id[set_id] = deduped
    return LovEntryIndex(by_set_id=by_set_id)


async def fetch_lov_entry_index(client: BackstopClient) -> LovEntryIndex:
    """Source 1: fetch every LOV entry once and index it by set.

    Failure is not fatal. Allowed values are an enrichment on top of a schema that is already
    usable for reads, so a `/lov-entries` outage degrades picklists to "no known options"
    rather than failing the whole schema refresh.
    """
    try:
        page = await client.paginate(
            _LOV_ENTRIES_PATH,
            max_records=None,
            schema=BackstopApiResource[LovEntryAttributes],
        )
    except Exception:
        logger.warning("custom_fields.lov_entries.fetch_failed", exc_info=True)
        return EMPTY_LOV_INDEX

    index = build_lov_entry_index(page.items)
    logger.info(
        "custom_fields.lov_entries.indexed",
        extra={"entries": len(page.items), "sets": len(index.by_set_id)},
    )
    return index


def included_set_entries(
    included: list[dict[str, object]], lov_set_id: str | None
) -> tuple[AllowedValue, ...]:
    """Source 2: entries carried inline by a side-loaded `included` set resource."""
    if lov_set_id is None:
        return ()
    for resource in included:
        if str(resource.get("id", "")) != lov_set_id:
            continue
        attributes = as_object_dict(resource.get("attributes"))
        if attributes is None:
            continue
        values = inline_allowed_values(attributes, attributes.get("selectOptions"))
        if values:
            return values
    return ()


def allowed_values_for(
    *,
    lov_set_id: str | None,
    lov_index: LovEntryIndex,
    included: list[dict[str, object]],
    inline_lov_set: object | None,
    inline_select_options: object | None,
) -> tuple[AllowedValue, ...]:
    """Best available allowed values for one definition, trying each source in turn."""
    from_entries = lov_index.allowed_values(lov_set_id)
    if from_entries:
        return from_entries

    from_included = included_set_entries(included, lov_set_id)
    if from_included:
        return from_included

    return inline_allowed_values(inline_lov_set, inline_select_options)
