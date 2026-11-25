from pydantic import Field

from kyckr_mcp.contexts.replies import KyckrModel


class Normalized(KyckrModel):
    """A registry value, as the registry states it and as Kyckr standardizes it."""

    original: str | None = Field(None, description="As the registry states it.")
    normalized: str | None = Field(
        None,
        description=(
            "Kyckr's standard value. A date is ISO 8601, `YYYY-MM-DD`, or `YYYY-MM` when the "
            "registry gives no day."
        ),
    )


class Address(KyckrModel):
    """An address at the registry."""

    type: str | None = Field(None, description="The kind of address, such as `Head Office`.")
    full_address: str | None = Field(None, description="The whole address on one line.")
    street_number: str | None = Field(None, description="The number on the street.")
    street_name: str | None = Field(None, description="The street.")
    city: str | None = Field(None, description="The city or town.")
    postcode: str | None = Field(None, description="The postal code.")
    region: str | None = Field(None, description="The region, such as a US state or UK county.")
    country: str | None = Field(None, description="The country.")
    iso_code: str | None = Field(None, description="The jurisdiction, ISO 3166 alpha-2.")


class Activity(KyckrModel):
    """An industry classification of the company."""

    code: str | None = Field(None, description="The activity code.")
    description: str | None = Field(None, description="What the code stands for.")
    classification_scheme: str | None = Field(
        None, description="The scheme of the code, such as NAICS or NACErev2."
    )
    type: str | None = Field(None, description="Whether the activity is primary or secondary.")
