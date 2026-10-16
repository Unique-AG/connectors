from typing import Annotated

from pydantic import BeforeValidator, Field, StringConstraints

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _blank_to_none(value: object) -> object:
    return (value.strip() or None) if isinstance(value, str) else value


def _iso_code(value: object) -> object:
    return _blank_to_none(value.upper() if isinstance(value, str) else value)


def _order_id(value: object) -> object:
    return str(value).strip() if isinstance(value, str | int) else value


KyckrId = Annotated[
    _Text,
    Field(
        description=(
            "Kyckr company id returned by `search_companies` as the result `id`, e.g. "
            '"GB|MTE2NTUyOTA". Pass the exact value from search; do not construct or modify it.'
        )
    ),
]
ProductId = Annotated[
    _Text,
    Field(
        description=(
            "Product id of the document to order. Use the `id` of an entry returned by "
            "`list_company_documents`. Do not construct or guess."
        )
    ),
]
OrderId = Annotated[
    str | int,
    BeforeValidator(_order_id),
    Field(
        min_length=1,
        description=(
            "Order id returned by `create_document_order.data.orderId` or seen in "
            "`list_orders.data.orders[].orderId`. May be a string or a number, pass it as-is."
        ),
    ),
]
IsoCode = Annotated[
    Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{2}$")] | None,
    BeforeValidator(_iso_code),
    Field(description="Optional ISO 3166 alpha-2 jurisdiction code, e.g. GB or AU."),
]
Name = Annotated[
    str | None, BeforeValidator(_blank_to_none), Field(description="Company name to search for.")
]
CompanyNumber = Annotated[
    str | None,
    BeforeValidator(_blank_to_none),
    Field(description="Company registration number to search for."),
]
ContinuationKey = Annotated[
    str | None,
    BeforeValidator(_blank_to_none),
    Field(
        description=(
            "Opaque pagination token from a previous response. Pass it back to fetch the next "
            "page. Omit on the first call."
        )
    ),
]
StartDate = Annotated[
    str | None,
    BeforeValidator(_blank_to_none),
    Field(description="Earliest order date to include, ISO 8601, forwarded to Kyckr as given."),
]
EndDate = Annotated[
    str | None,
    BeforeValidator(_blank_to_none),
    Field(description="Latest order date to include, ISO 8601, forwarded to Kyckr as given."),
]
