from datetime import date

from backstop_mcp.features.accounts.project import (
    AccountApiResponse,
    account_is_open,
    project_account,
    project_owner,
    split_open,
)
from backstop_mcp.features.accounts.types import AccountAttributes, AccountOwner, AccountRecord
from tests.helpers import resource

_AccountResource = AccountApiResponse


def _account(
    account_id: str,
    *,
    owner_id: str | None = None,
    investor_type_id: str | None = None,
    product_id: str | None = None,
    **attributes: object,
) -> dict[str, object]:
    relationships: dict[str, object] = {}
    if owner_id is not None:
        relationships["owner"] = {"data": {"type": "contacts", "id": owner_id}}
    if investor_type_id is not None:
        relationships["investorType"] = {"data": {"type": "investor-types", "id": investor_type_id}}
    if product_id is not None:
        relationships["product"] = {"data": {"type": "products", "id": product_id}}
    return {
        "id": account_id,
        "type": "accounts",
        "attributes": attributes,
        "relationships": relationships,
    }


def _owner(
    owner_id: str,
    *,
    name: str,
    resource_type: str | None = None,
    json_api_type: str = "contacts",
    specific_id: str | None = None,
) -> dict[str, object]:
    specific: dict[str, object] | None = (
        None
        if resource_type is None
        else {"resourceType": resource_type, "resourceId": specific_id or owner_id}
    )
    return resource(owner_id, json_api_type, name=name, specificResource=specific)


class TestAccountIsOpen:
    def test_absent_closed_date_is_open(self) -> None:
        assert account_is_open(AccountAttributes.model_validate({"name": "Open Account"})) is True

    def test_present_closed_date_is_closed(self) -> None:
        assert (
            account_is_open(
                AccountAttributes.model_validate({"name": "Closed", "closedDate": "2020-01-15"})
            )
            is False
        )

    def test_null_closed_date_is_closed(self) -> None:
        assert (
            account_is_open(
                AccountAttributes.model_validate({"name": "Closed", "closedDate": None})
            )
            is False
        )


class TestProjectOwner:
    def test_org_owner_uses_specific_resource_type(self) -> None:
        owner = project_owner(
            _owner("341688185", name="PSP Investments", resource_type="organizations")
        )

        assert owner == AccountOwner(
            id="341688185",
            name="PSP Investments",
            resource_type="organizations",
        )

    def test_specific_resource_supplies_the_id_that_goes_with_its_type(self) -> None:
        owner = project_owner(
            _owner(
                "contact-1",
                name="PSP Investments",
                resource_type="organizations",
                specific_id="341688185",
            )
        )

        assert owner == AccountOwner(
            id="341688185",
            name="PSP Investments",
            resource_type="organizations",
        )

    def test_a_specific_resource_without_a_type_leaves_the_envelope_identity(self) -> None:
        owner = project_owner(
            resource(
                "contact-1",
                "contacts",
                name="PSP Investments",
                specificResource={"resourceId": "341688185"},
            )
        )

        assert owner == AccountOwner(
            id="contact-1", name="PSP Investments", resource_type="contacts"
        )

    def test_person_owner_keeps_json_api_type(self) -> None:
        owner = project_owner(resource("99", "people", name="Ada Lovelace"))

        assert owner == AccountOwner(id="99", name="Ada Lovelace", resource_type="people")

    def test_blank_id_is_dropped(self) -> None:
        assert project_owner({"id": "  ", "type": "contacts", "attributes": {}}) is None


class TestProjectAccount:
    def test_projects_includes_and_status_fields(self) -> None:
        included = [
            _owner("341688185", name="PSP Investments", resource_type="organizations"),
            resource("10", "investor-types", name="Fund of Funds"),
            resource(
                "1292283",
                "products",
                name="Capstone Global Unconstrained Portfolio",
                configuration={"productShortName": "CGUP"},
            ),
        ]
        resource_body = _account(
            "27871657",
            owner_id="341688185",
            investor_type_id="10",
            product_id="1292283",
            name="PSP CGUP",
            currency="USD",
            accountStartDate="2019-03-01",
            ownershipType="Direct",
            investorQualification="QP",
            isEmployeeAccount=False,
            isGpAccount=False,
            amlCheckComplete=True,
            newIssueEligible=True,
            usDomiciled=False,
        )

        record = project_account(
            _AccountResource.model_validate(resource_body),
            included=included,
        )

        assert record.id == "27871657"
        assert record.name == "PSP CGUP"
        assert record.owner == AccountOwner(
            id="341688185",
            name="PSP Investments",
            resource_type="organizations",
        )
        assert record.investor_type is not None
        assert record.investor_type.name == "Fund of Funds"
        assert record.product is not None
        assert record.product.short_name == "CGUP"
        assert record.currency == "USD"
        assert record.account_start_date == date(2019, 3, 1)
        assert record.is_open is True
        assert record.aml_check_complete is True

    def test_missing_includes_leave_fields_unset(self) -> None:
        record = project_account(
            _AccountResource.model_validate(_account("1", name="Solo")),
            included=[],
        )

        assert record.owner is None
        assert record.investor_type is None
        assert record.product is None
        assert record.is_open is True

    def test_product_include_with_null_relationships_still_projects(self) -> None:
        included: list[dict[str, object]] = [
            {
                "id": "1292283",
                "type": "products",
                "attributes": {
                    "name": "Capstone Global Unconstrained Portfolio",
                    "configuration": {"productShortName": "CGUP"},
                },
                "relationships": None,
            }
        ]
        record = project_account(
            _AccountResource.model_validate(_account("1", product_id="1292283", name="Row")),
            included=included,
        )

        assert record.product is not None
        assert record.product.short_name == "CGUP"


class TestSplitOpen:
    def _record(self, account_id: str, *, is_open: bool) -> AccountRecord:
        return AccountRecord(id=account_id, is_open=is_open)

    def test_default_drops_closed_and_counts_them(self) -> None:
        listing = split_open(
            (self._record("1", is_open=True), self._record("2", is_open=False)),
            include_closed=False,
        )

        assert [account.id for account in listing.accounts] == ["1"]
        assert listing.closed_omitted == 1

    def test_include_closed_keeps_every_row(self) -> None:
        listing = split_open(
            (self._record("1", is_open=True), self._record("2", is_open=False)),
            include_closed=True,
        )

        assert [account.id for account in listing.accounts] == ["1", "2"]
        assert listing.closed_omitted == 0
