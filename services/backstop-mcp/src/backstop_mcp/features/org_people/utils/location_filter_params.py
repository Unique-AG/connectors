from backstop_mcp.features.org_people.inputs import LocationFilter


def location_filter_params(location_filter: LocationFilter | None) -> dict[str, str]:
    """The part of `location_filter` Backstop can filter on, sent exactly as the caller wrote it.

    Of the `contactLocations` fields only `city` and `address` are filter fields, and both are
    `eq`: exact and case-sensitive, no `like`, no `in`. Every other field is `400 Invalid filter
    field`, so it is left to the in-memory match. The filter reaches the primary location too:
    it is one of the side-loaded `contactLocations`, as well as inlined on the party record.
    """
    if location_filter is None:
        return {}
    params: dict[str, str] = {}
    if location_filter.city is not None:
        params["filter[contactLocations.city][eq]"] = location_filter.city
    if location_filter.street_address is not None:
        params["filter[contactLocations.address][eq]"] = location_filter.street_address
    return params
