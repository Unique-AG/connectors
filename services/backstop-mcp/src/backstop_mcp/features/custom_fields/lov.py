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
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import ClassVar, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.custom_fields.types import AllowedValue, LovEntryAttributes

logger = logging.getLogger(__name__)

_LOV_ENTRIES_PATH = "/lov-entries"

_LABEL_KEYS = ("display", "defaultDisplay", "label", "name", "value", "displayName", "display_name")
_ENTRY_COLLECTION_KEYS = ("entries", "lovEntries", "viewableEntries", "options", "values")


def _clean(value: object) -> str | None:
    """A stripped non-empty string, or None — the rule these payloads are read under."""
    return (value.strip() or None) if isinstance(value, str) else None


def _first_label(payload: Mapping[str, object]) -> str | None:
    """First non-blank label among the known keys.

    Not `AliasChoices`: that binds the first key that is *present*, so a null or blank
    `display` would shadow a perfectly good `defaultDisplay` underneath it.
    """
    return next(
        (label for key in _LABEL_KEYS if (label := _clean(payload.get(key))) is not None), None
    )


class _InlineOption(BaseModel):
    """One picklist option, in any of the three shapes Backstop inlines it in.

    A bare label string; a flat object carrying one of `_LABEL_KEYS`; or a JSON:API resource
    whose label sits under `attributes` while its id stays on the envelope. Normalising all
    three here is what lets the callers below stay free of hand-rolled narrowing.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str | None = None
    label: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, value: object) -> object:
        if isinstance(value, str):
            return {"label": _clean(value)}
        if not isinstance(value, Mapping):
            # Carries neither a label nor an id, so it drops out in `as_allowed_value` rather
            # than failing the whole list it arrived in.
            return {}
        payload = cast("Mapping[str, object]", value)
        attributes = payload.get("attributes")
        inner = (
            cast("Mapping[str, object]", attributes) if isinstance(attributes, Mapping) else payload
        )
        # A side-loaded resource keeps its id on the envelope; `attributes` alone often omits it.
        option_id = inner.get("id", payload.get("id"))
        return {
            "id": str(option_id) if option_id is not None else None,
            "label": _first_label(inner),
        }

    def as_allowed_value(self) -> AllowedValue | None:
        """`None` when the option carries neither a label nor an id to fall back on."""
        if self.label is not None:
            return AllowedValue(id=self.id, label=self.label)
        if self.id is not None:
            return AllowedValue(id=self.id, label=self.id)
        return None


class _InlineOptionSet(BaseModel):
    """A `lovSet`/`selectOptions` attribute, whether it arrives as a list or as an object.

    As an object the options hide under one of several collection keys, or under a JSON:API
    `data` that is itself either a list or a single resource. Each of those is resolved here,
    so `inline_allowed_values` reads as a concatenation instead of a shape probe.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    options: list[_InlineOption] = Field(default_factory=list)
    select_options: list[_InlineOption] = Field(default_factory=list)
    data: list[_InlineOption] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _collect(cls, value: object) -> object:
        if isinstance(value, list):
            return {"options": cast("list[object]", value)}
        if not isinstance(value, Mapping):
            return {}
        payload = cast("Mapping[str, object]", value)
        options: list[object] = []
        for key in _ENTRY_COLLECTION_KEYS:
            items = payload.get(key)
            if isinstance(items, list) and items:
                options = cast("list[object]", items)
                break
        raw_data = payload.get("data")
        data: list[object] = []
        if isinstance(raw_data, list):
            data = cast("list[object]", raw_data)
        elif isinstance(raw_data, Mapping):
            data = [cast("Mapping[str, object]", raw_data)]
        raw_select = payload.get("selectOptions")
        return {
            "options": options,
            "select_options": (
                cast("list[object]", raw_select) if isinstance(raw_select, list) else []
            ),
            "data": data,
        }

    def allowed_values(self) -> list[AllowedValue]:
        return [
            value
            for option in (*self.options, *self.select_options, *self.data)
            if (value := option.as_allowed_value()) is not None
        ]


def _dedupe_by_label(values: Iterable[AllowedValue]) -> tuple[AllowedValue, ...]:
    by_label: dict[str, AllowedValue] = {}
    for value in values:
        by_label.setdefault(value.label, value)
    return tuple(by_label.values())


def inline_allowed_values(
    lov_set: object | None, select_options: object | None
) -> tuple[AllowedValue, ...]:
    """Source 3: options inlined on the definition's own attributes."""
    return _dedupe_by_label(
        _InlineOptionSet.model_validate(select_options).allowed_values()
        + _InlineOptionSet.model_validate(lov_set).allowed_values()
    )


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
        # `_InlineOptionSet` reads `selectOptions` off the attributes itself.
        values = inline_allowed_values(resource.get("attributes"), None)
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
