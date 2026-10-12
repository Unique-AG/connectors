"""List Backstop accounts for one product.

`get_product_investors` is the consumer. By-product listing uses `filter[product.id][eq]`.
Open means the `closedDate` key is absent.

The listing asks for `fields=` and pages in parallel. `fields=` drops the whole `relationships`
block — except for the relationships named in `include=`, which keep their `data` linkage.
Why `closedDate` stays meaningful under `fields=` is noted on `ACCOUNT_LISTING_FIELDS`.
`regularCustomFieldValues` is requested unless `exclude_custom_fields` is set.
`owner_ids` (a party id or its contacts envelope id) keeps only those owners' accounts,
before the open/closed split, so `closed_omitted` counts their closed accounts only.
`spans_by_owner` and `owners` on the payload are also taken before the split, so tenure counts
closed accounts, and owners with only closed accounts stay known, whatever `include_closed` is.
"""

from collections.abc import Sequence

from backstop_mcp.backstop_client import BackstopClient, Included
from backstop_mcp.features.accounts.api_responses import (
    ACCOUNT_LISTING_FIELDS,
    AccountApiResource,
)
from backstop_mcp.features.accounts.internal_dto import AccountSpanDto, ResolvedProductDto
from backstop_mcp.features.accounts.responses import (
    AccountRowResponse,
    ProductAccountsResponse,
    ProductListingResponse,
    ProductRefResponse,
    closed_hint,
)
from backstop_mcp.features.custom_fields import stored_custom_field_values


class GetAccountsForProductQuery:
    """Accounts in one product, with owners, and no figures. The tool adds investors."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(
        self,
        *,
        product: ResolvedProductDto,
        include_closed: bool = False,
        exclude_custom_fields: bool = False,
        owner_ids: frozenset[str] | None = None,
    ) -> ProductAccountsResponse:
        fields = ACCOUNT_LISTING_FIELDS
        if not exclude_custom_fields:
            fields = f"{fields},regularCustomFieldValues"
        page = await self._client.paginate(
            "/accounts",
            schema=AccountApiResource,
            params={
                "filter[product.id][eq]": product.id,
                "include": "owner,investorType",
                "fields": fields,
            },
            max_records=None,
            page_size=100,
            parallel=True,
        )
        included = Included(page.included)
        rows = tuple(
            AccountRowResponse.from_resource(
                resource,
                included=included,
                custom_field_values=None
                if exclude_custom_fields
                else stored_custom_field_values(resource.attributes.regular_custom_field_values)
                or None,
            )
            for resource in page.items
        )
        if owner_ids is not None:
            rows = tuple(
                row for row in rows if row.owner is not None and row.owner.has_id(owner_ids)
            )
        kept = rows if include_closed else tuple(row for row in rows if row.is_open)
        closed_omitted = 0 if include_closed else len(rows) - len(kept)
        return ProductAccountsResponse(
            listing=ProductListingResponse(
                product=ProductRefResponse.from_product(product),
                accounts=kept,
                closed_omitted=closed_omitted,
                include_closed_hint=closed_hint(
                    closed_omitted=closed_omitted,
                    returned=len(kept),
                    subject="product",
                ),
            ),
            spans_by_owner=self._spans_by_owner(rows),
            owners={row.owner.id: row.owner for row in rows if row.owner is not None},
        )

    def _spans_by_owner(
        self, rows: Sequence[AccountRowResponse]
    ) -> dict[str, tuple[AccountSpanDto, ...]]:
        grouped: dict[str, list[AccountSpanDto]] = {}
        for row in rows:
            if row.owner is None:
                continue
            grouped.setdefault(row.owner.id, []).append(
                AccountSpanDto(
                    start=row.account_start_date, end=row.closed_date, is_open=row.is_open
                )
            )
        return {owner_id: tuple(spans) for owner_id, spans in grouped.items()}
