from backstop_mcp.features.accounts.time_series_name import (
    ACCOUNT_SERIES,
    PRODUCT_SERIES,
    TimeSeriesEntityType,
    TimeSeriesName,
)


def raise_if_invalid_series(entity_type: TimeSeriesEntityType, series: TimeSeriesName) -> None:
    """Raise when `series` is not on this entity type's swagger enum.

    The tool parameter type is the union of both enums, so pairing is this check rather than
    pydantic's. An unrecognized path segment is silently a 404 on some Backstop versions.

    `get_time_series` calls this on its arguments before it spends a product resolve.
    """
    allowed = ACCOUNT_SERIES if entity_type == "accounts" else PRODUCT_SERIES
    if series in allowed:
        return
    names = ", ".join(sorted(allowed))
    raise ValueError(f"series {series!r} is not valid for {entity_type}: {names}")
