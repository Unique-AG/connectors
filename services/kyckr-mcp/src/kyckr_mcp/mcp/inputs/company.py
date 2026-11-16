from typing import Annotated

from pydantic import BeforeValidator
from pydantic import Field
from pydantic import StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def blank_to_none(value: object) -> object:
    return (value.strip() or None) if isinstance(value, str) else value


def _iso_code(value: object) -> object:
    return blank_to_none(value.upper() if isinstance(value, str) else value)


KyckrId = Annotated[
    Text,
    Field(
        description=(
            "Kyckr company id returned by `search_companies` as the result `id`, e.g. "
            '"GB|MTE2NTUyOTA". Pass the exact value from search; do not construct or modify it.'
        )
    ),
]
IsoCode = Annotated[
    Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{2}$")] | None,
    BeforeValidator(_iso_code),
    Field(description="Optional ISO 3166 alpha-2 jurisdiction code, e.g. GB or AU."),
]
Name = Annotated[
    str | None, BeforeValidator(blank_to_none), Field(description="Company name to search for.")
]
CompanyNumber = Annotated[
    str | None,
    BeforeValidator(blank_to_none),
    Field(description="Company registration number to search for."),
]
ContinuationKey = Annotated[
    str | None,
    BeforeValidator(blank_to_none),
    Field(
        description=(
            "Opaque pagination token from a previous response. Pass it back to fetch the next "
            "page. Omit on the first call."
        )
    ),
]
