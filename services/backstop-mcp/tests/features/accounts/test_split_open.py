from backstop_mcp.features.accounts import AccountRecordDto, split_open


def _record(account_id: str, *, is_open: bool) -> AccountRecordDto:
    return AccountRecordDto(id=account_id, is_open=is_open)


class TestSplitOpen:
    def test_default_drops_closed_and_counts_them(self) -> None:
        listing = split_open(
            (_record("1", is_open=True), _record("2", is_open=False)),
            include_closed=False,
        )

        assert [account.id for account in listing.accounts] == ["1"]
        assert listing.closed_omitted == 1

    def test_include_closed_keeps_every_row(self) -> None:
        listing = split_open(
            (_record("1", is_open=True), _record("2", is_open=False)),
            include_closed=True,
        )

        assert [account.id for account in listing.accounts] == ["1", "2"]
        assert listing.closed_omitted == 0
