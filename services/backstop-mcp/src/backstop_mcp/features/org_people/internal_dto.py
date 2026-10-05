"""Internal projections for the org_people searches."""

from pydantic import BaseModel

from backstop_mcp.lenient import LenientStr

__all__ = ["LocationDto"]


class LocationDto(BaseModel):
    """One address of a party, whichever Backstop record it was read from.

    A `contact-locations` side-load and the primary-location copy on the party record spell the
    same address differently (`address` / `streetAddress`) and only the side-load has a country
    code. Both are read into this one shape, so a location filter matches them the same way.
    Field names are those of `ContactLocationResponse`, which a row publishes these as.
    """

    id: str | None = None
    location_title: LenientStr = None
    address: LenientStr = None
    city: LenientStr = None
    state: LenientStr = None
    country: LenientStr = None
    country_code: LenientStr = None
    postal_code: LenientStr = None
    phone: LenientStr = None
    is_primary: bool = False
