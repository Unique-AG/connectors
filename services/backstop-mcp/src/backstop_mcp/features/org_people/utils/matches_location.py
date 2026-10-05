from collections.abc import Sequence

from backstop_mcp.features.org_people.inputs import LocationFilter
from backstop_mcp.features.org_people.internal_dto import LocationDto

_ISO_CODE_LENGTH = 2


def matches_location(locations: Sequence[LocationDto], location_filter: LocationFilter) -> bool:
    """True when one of `locations` satisfies every field set on `location_filter`.

    The fields AND within a single location: `city=London` with `country=Canada` means a London in
    Canada, not a London office and some other Canadian one. `city` and `street_address` are also
    sent to Backstop, which compares them exactly and case-sensitively, so they are compared the
    same way here. The other text fields are casefolded substrings; a missing value never matches
    a set field. A two-letter `country` is an ISO code and is compared exactly, never as a
    substring. `primary_only` narrows the candidates to the primary location.
    """
    candidates = (
        [location for location in locations if location.is_primary]
        if location_filter.primary_only
        else locations
    )
    return any(_satisfies(location, location_filter) for location in candidates)


def _satisfies(location: LocationDto, location_filter: LocationFilter) -> bool:
    return (
        _same(location.city, location_filter.city)
        and _contains(location.state, location_filter.state)
        and _contains(location.postal_code, location_filter.postal_code)
        and _same(location.address, location_filter.street_address)
        and _contains(location.location_title, location_filter.location_title)
        and _in_country(location, location_filter.country)
    )


def _in_country(location: LocationDto, country: str | None) -> bool:
    if country is None:
        return True
    if len(country) == _ISO_CODE_LENGTH and country.isalpha():
        needle = country.casefold()
        return needle in (
            (location.country_code or "").casefold(),
            (location.country or "").casefold(),
        )
    return _contains(location.country, country)


def _same(value: str | None, expected: str | None) -> bool:
    return expected is None or value == expected


def _contains(value: str | None, needle: str | None) -> bool:
    return needle is None or needle.casefold() in (value or "").casefold()
