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
from dataclasses import dataclass

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.coerce import as_clean_str, as_object_dict, as_object_list
from backstop_mcp.features.custom_fields.types import AllowedValue, LovEntryAttributes

logger = logging.getLogger(__name__)

_LOV_ENTRIES_PATH = "/lov-entries"

# Keys an inlined option object may use for its human label, most specific first.
_LABEL_KEYS = ("display", "defaultDisplay", "label", "name", "value", "displayName", "display_name")
# Keys under which an inlined set object may nest its entries.
_ENTRY_COLLECTION_KEYS = ("entries", "lovEntries", "viewableEntries", "options", "values")


def _label_from_option(option: object) -> str | None:
    text = as_clean_str(option)
    if text is not None:
        return text
    option_dict = as_object_dict(option)
    if option_dict is None:
        return None
    for key in _LABEL_KEYS:
        label = as_clean_str(option_dict.get(key))
        if label is not None:
            return label
    option_id = option_dict.get("id")
    return str(option_id) if option_id is not None else None


def _id_from_option(option: object) -> str | None:
    option_dict = as_object_dict(option)
    if option_dict is None or option_dict.get("id") is None:
        return None
    return str(option_dict["id"])


class _AllowedValueBuilder:
    """Accumulates allowed values, deduplicating by label and preserving insertion order."""

    def __init__(self) -> None:
        self._values: list[AllowedValue] = []
        self._seen: set[str] = set()

    def add(self, option: object) -> None:
        label = _label_from_option(option)
        if label is None or label in self._seen:
            return
        self._seen.add(label)
        self._values.append(AllowedValue(id=_id_from_option(option), label=label))

    def add_entry(self, entry_id: str | None, label: str) -> None:
        if label in self._seen:
            return
        self._seen.add(label)
        self._values.append(AllowedValue(id=entry_id, label=label))

    def build(self) -> tuple[AllowedValue, ...]:
        return tuple(self._values)


def inline_allowed_values(
    lov_set: object | None, select_options: object | None
) -> tuple[AllowedValue, ...]:
    """Source 3: options inlined on the definition's own attributes."""
    builder = _AllowedValueBuilder()

    for option in as_object_list(select_options):
        builder.add(option)

    lov_dict = as_object_dict(lov_set)
    if lov_dict is None:
        for option in as_object_list(lov_set):
            builder.add(option)
        return builder.build()

    for key in _ENTRY_COLLECTION_KEYS:
        for option in as_object_list(lov_dict.get(key)):
            builder.add(option)

    # A side-loaded set arrives as a JSON:API resource, so the useful fields are one level
    # down under `attributes`.
    data = lov_dict.get("data")
    data_list = as_object_list(data)
    if data_list:
        for item in data_list:
            builder.add(_attributes_or_self(item))
        return builder.build()

    data_dict = as_object_dict(data)
    if data_dict is not None:
        builder.add(_attributes_or_self(data_dict))
    return builder.build()


def _attributes_or_self(item: object) -> object:
    item_dict = as_object_dict(item)
    if item_dict is None:
        return item
    attributes = item_dict.get("attributes")
    return attributes if as_object_dict(attributes) is not None else item


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
        builder = _AllowedValueBuilder()
        for entry in sorted(set_entries, key=_entry_sort_key):
            attributes = entry.attributes
            label = attributes.display or attributes.default_display or attributes.code
            if label is None:
                continue
            builder.add_entry(entry.id, label)
        values = builder.build()
        if values:
            by_set_id[set_id] = values
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
