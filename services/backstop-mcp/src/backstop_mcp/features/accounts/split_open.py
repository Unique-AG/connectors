"""Keep or drop closed accounts after listing, counting how many were omitted."""

from collections.abc import Sequence

from backstop_mcp.features.accounts.internal_dto import AccountListingDto, AccountRecordDto


def split_open(records: Sequence[AccountRecordDto], *, include_closed: bool) -> AccountListingDto:
    if include_closed:
        return AccountListingDto(accounts=tuple(records), closed_omitted=0)
    open_accounts = tuple(record for record in records if record.is_open)
    return AccountListingDto(
        accounts=open_accounts,
        closed_omitted=len(records) - len(open_accounts),
    )
