"""Published tool input for the firm-wide searches."""

from typing import Self

from pydantic import BaseModel, Field, model_validator

from backstop_mcp.lenient import LenientStr

__all__ = ["LocationFilter"]


class LocationFilter(BaseModel):
    """One location a party must have. Every field set must match the same location."""

    city: LenientStr = Field(
        default=None,
        description=(
            "Exact city name as stored, case-sensitive: 'London', not 'london' or 'Lond'. "
            "Sent to Backstop."
        ),
    )
    country: LenientStr = Field(
        default=None,
        description=(
            "Whole words of the country, any case, stored as the full name ('United Arab "
            "Emirates', 'United States of America'). Spelling varies between records "
            "('United States', 'United States Of America'): pass the shortest distinctive "
            "words — 'United States' matches both, 'Niger' does not match 'Nigeria'. A "
            "two-letter ISO code ('US', 'GB') also matches, exactly."
        ),
    )
    state: LenientStr = Field(
        default=None,
        description=(
            "The whole state or region as stored, any case, usually the code ('MA', 'NY'). "
            "Not a substring: 'Kansas' does not match 'Arkansas'."
        ),
    )
    postal_code: LenientStr = Field(default=None, description="Substring of the postal code.")
    street_address: LenientStr = Field(
        default=None,
        description=(
            "Exact street address as stored, case-sensitive, suite and floor included. "
            "Sent to Backstop."
        ),
    )
    location_title: LenientStr = Field(
        default=None,
        description="Substring of the location's title, such as 'Business' or 'London'.",
    )
    primary_only: bool = Field(
        default=False,
        description=(
            "False (default): any of the party's locations may match. True: only its primary "
            "location counts, so an office that is not the primary one does not match."
        ),
    )

    @model_validator(mode="after")
    def _requires_a_field(self) -> Self:
        if not any(
            (
                self.city,
                self.country,
                self.state,
                self.postal_code,
                self.street_address,
                self.location_title,
            )
        ):
            raise ValueError("location_filter needs a city, country, state, or other text field")
        return self
