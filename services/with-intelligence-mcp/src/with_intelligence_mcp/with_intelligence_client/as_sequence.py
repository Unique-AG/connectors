"""Coerce With Intelligence nested fields whose OpenAPI type disagrees with the wire payload.

Evidence is the public spec snapshot (`tests/spec/wi_schemas.json`) against a recorded
`GET /v3/investors/{id}` (`tests/features/investors/recordings/investor-extended.json`) and the
person-role schema:

- `consultants` is declared `array<InvestorConsultant>` and delivered as
  `{"0": {...}, "1": {...}}`.
- `investment_strategies` is declared an object and delivered as a list.
- `latest_aum.ranges_usd` is declared a single `InvestorLatestAumRangesUsd` and delivered as a
  list of those objects.
- `PersonPersonRole.specialisms` is declared a single `Classification` and delivered as a list.

`SEQUENCE` (list fields) and `SINGLE` (object fields) accept either encoding. They are attached
to every nested field on the wire models so an additional mismatch of the same kind parses.

An index-keyed object is one whose keys are all decimal digits; any other object is one record.
That distinction is required: flattening via `.values()` would turn
`{"id": 4, "name": "Real Assets"}` into `[4, "Real Assets"]`. Digit keys are not always indexes
— `asset_allocation_breakdown` is specified as a map keyed by asset-class id — so `SEQUENCE`
must not be applied to that shape.
"""

from typing import cast

from pydantic import BeforeValidator


def as_sequence(value: object) -> object:
    """Return a list: keep a JSON array, flatten an index-keyed object, wrap a single record.

    Index-keyed objects have only decimal-digit keys and are emitted in numeric key order.
    Any other object is wrapped as a one-element list.
    """
    if not isinstance(value, dict):
        return value
    entries = cast(dict[str, object], value)
    if not entries:
        return []
    if all(key.isdigit() for key in entries):
        return [entries[key] for key in sorted(entries, key=int)]
    return [entries]


def as_single(value: object) -> object:
    """Return one object: keep a mapping, unwrap a one-element list, map `[]` to `None`.

    A list longer than one is reduced to its first element.
    """
    if not isinstance(value, list):
        return value
    entries = cast(list[object], value)
    return entries[0] if entries else None


SEQUENCE = BeforeValidator(as_sequence)
SINGLE = BeforeValidator(as_single)
