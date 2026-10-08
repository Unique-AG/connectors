from collections.abc import Sequence

from backstop_mcp.features.org_people.api_responses import (
    LocationResource,
    OrganizationAttributes,
    PersonAttributes,
)
from backstop_mcp.features.org_people.internal_dto import LocationDto


def party_locations(
    attributes: PersonAttributes | OrganizationAttributes,
    linked: Sequence[LocationResource],
) -> tuple[LocationDto, ...]:
    """Every address of a party, primary first.

    `linked` are the side-loaded `contact-locations`. The party record also inlines a copy of
    its primary location; that copy stands in for the primary only when no side-loaded location
    is marked primary (the side-load was not requested, or Backstop sent none), so the same
    address is never listed twice.
    """
    side_loaded = tuple(
        LocationDto(
            id=resource.id,
            location_title=resource.attributes.location_title,
            address=resource.attributes.address,
            city=resource.attributes.city,
            state=resource.attributes.state,
            country=resource.attributes.country,
            country_code=resource.attributes.country_code,
            postal_code=resource.attributes.postal_code,
            phone=resource.attributes.phone,
            is_primary=resource.attributes.is_primary is True,
        )
        for resource in linked
    )
    if not any(location.is_primary for location in side_loaded):
        inlined = LocationDto(
            location_title=attributes.location_title,
            address=attributes.street_address,
            city=attributes.city,
            state=attributes.state,
            country=attributes.country,
            postal_code=attributes.postal_code,
            is_primary=True,
        )
        if inlined.model_dump(exclude={"is_primary"}, exclude_none=True):
            side_loaded = (inlined, *side_loaded)
    return tuple(sorted(side_loaded, key=lambda location: not location.is_primary))
