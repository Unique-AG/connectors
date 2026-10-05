from collections.abc import Sequence

from backstop_mcp.features.org_people.inputs import LocationFilter
from backstop_mcp.features.org_people.internal_dto import LocationDto


def matches_location(locations: Sequence[LocationDto], location_filter: LocationFilter) -> bool:
    """True when one of `locations` satisfies every field set on `location_filter`.

    The fields AND within a single location: `city=London` with `country=Canada` means a London in
    Canada, not a London office and some other Canadian one. `city` and `street_address` are also
    sent to Backstop, which compares them exactly and case-sensitively, so they are compared the
    same way here. The other text fields are casefolded substrings; a missing value never matches
    a set field. `country` also accepts the two-letter code exactly. `primary_only` narrows the
    candidates to the primary location.
    """
    candidates = (
        [location for location in locations if location.is_primary]
        if location_filter.primary_only
        else locations
    )
    return any(_satisfies(location, location_filter) for location in candidates)


def _satisfies(location: LocationDto, location_filter: LocationFilter) -> bool:
    country = location_filter.country
    return (
        _same(location.city, location_filter.city)
        and _contains(location.state, location_filter.state)
        and _contains(location.postal_code, location_filter.postal_code)
        and _same(location.address, location_filter.street_address)
        and _contains(location.location_title, location_filter.location_title)
        and (
            country is None
            or _contains(location.country, country)
            or (location.country_code or "").casefold() == country.casefold()
        )
    )


def _same(value: str | None, expected: str | None) -> bool:
    return expected is None or value == expected


def _contains(value: str | None, needle: str | None) -> bool:
    return needle is None or needle.casefold() in (value or "").casefold()
