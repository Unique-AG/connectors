from datetime import date

from backstop_mcp.backstop_client import Included
from backstop_mcp.features.accounts import (
    AccountApiResource,
    AccountOwnerDto,
    AccountRecordDto,
    AccountRowResponse,
    ResolvedProductDto,
)
from tests.helpers import resource


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


def _from_resource(
    body: dict[str, object],
    *,
    included: list[dict[str, object]] | None = None,
) -> AccountRecordDto:
    return AccountRecordDto.from_resource(
        AccountApiResource.model_validate(body),
        included=Included([] if included is None else included),
    )


class TestAccountAttributesWire:
    def test_accepts_qualification_object_and_eligibility_enum(self) -> None:
        record = _from_resource(
            _account(
                "1",
                name="Row",
                investorQualification={"status": "REG_UNKNOWN", "option": "UNKNOWN"},
                newIssueEligible="NOT_ELIGIBLE",
            )
        )

        assert record.investor_qualification is not None
        assert record.investor_qualification.status == "REG_UNKNOWN"
        assert record.investor_qualification.option == "UNKNOWN"
        assert record.new_issue_eligible == "NOT_ELIGIBLE"

    def test_qualification_may_omit_status(self) -> None:
        record = _from_resource(
            _account(
                "1",
                investorQualification={"option": "UNKNOWN"},
                newIssueEligible="N/A",
            )
        )

        assert record.investor_qualification is not None
        assert record.investor_qualification.status is None
        assert record.investor_qualification.option == "UNKNOWN"
        assert record.new_issue_eligible == "N/A"


class TestAccountIsOpen:
    def test_absent_closed_date_is_open(self) -> None:
        record = _from_resource(_account("1", name="Open Account"))
        assert record.is_open is True

    def test_present_closed_date_is_closed(self) -> None:
        record = _from_resource(_account("1", name="Closed", closedDate="2020-01-15"))
        assert record.is_open is False

    def test_null_closed_date_is_closed(self) -> None:
        record = _from_resource(_account("1", name="Closed", closedDate=None))
        assert record.is_open is False


class TestProjectOwner:
    def test_org_owner_uses_specific_resource_type(self) -> None:
        owner = AccountOwnerDto.from_included(
            _owner("341688185", name="PSP Investments", resource_type="organizations")
        )

        assert owner == AccountOwnerDto(
            id="341688185",
            name="PSP Investments",
            resource_type="organizations",
        )

    def test_specific_resource_supplies_the_id_that_goes_with_its_type(self) -> None:
        owner = AccountOwnerDto.from_included(
            _owner(
                "contact-1",
                name="PSP Investments",
                resource_type="organizations",
                specific_id="341688185",
            )
        )

        assert owner == AccountOwnerDto(
            id="341688185",
            name="PSP Investments",
            resource_type="organizations",
        )

    def test_a_specific_resource_without_a_type_leaves_the_envelope_identity(self) -> None:
        owner = AccountOwnerDto.from_included(
            resource(
                "contact-1",
                "contacts",
                name="PSP Investments",
                specificResource={"resourceId": "341688185"},
            )
        )

        assert owner == AccountOwnerDto(
            id="contact-1", name="PSP Investments", resource_type="contacts"
        )

    def test_person_owner_keeps_json_api_type(self) -> None:
        owner = AccountOwnerDto.from_included(resource("99", "people", name="Ada Lovelace"))

        assert owner == AccountOwnerDto(id="99", name="Ada Lovelace", resource_type="people")

    def test_blank_id_is_dropped(self) -> None:
        assert (
            AccountOwnerDto.from_included({"id": "  ", "type": "contacts", "attributes": {}})
            is None
        )


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
        record = _from_resource(
            _account(
                "27871657",
                owner_id="341688185",
                investor_type_id="10",
                product_id="1292283",
                name="PSP CGUP",
                currency="USD",
                accountStartDate="2019-03-01",
                ownershipType="Direct",
                investorQualification={"status": "REG_UNKNOWN", "option": "UNKNOWN"},
                isEmployeeAccount=False,
                isGpAccount=False,
                amlCheckComplete=True,
                newIssueEligible="ELIGIBLE",
                usDomiciled=False,
            ),
            included=included,
        )

        assert record.id == "27871657"
        assert record.name == "PSP CGUP"
        assert record.owner == AccountOwnerDto(
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
        assert record.investor_qualification is not None
        assert record.investor_qualification.status == "REG_UNKNOWN"
        assert record.investor_qualification.option == "UNKNOWN"
        assert record.new_issue_eligible == "ELIGIBLE"

    def test_missing_includes_leave_fields_unset(self) -> None:
        record = _from_resource(_account("1", name="Solo"))

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
        record = _from_resource(
            _account("1", product_id="1292283", name="Row"),
            included=included,
        )

        assert record.product is not None
        assert record.product.short_name == "CGUP"


class TestProductFromIncluded:
    def test_reads_nested_product_short_name(self) -> None:
        product = ResolvedProductDto.from_included(
            resource(
                "1292283",
                "products",
                name="Capstone Global Unconstrained Portfolio",
                configuration={"productShortName": "CGUP"},
            )
        )

        assert product == ResolvedProductDto(
            id="1292283",
            name="Capstone Global Unconstrained Portfolio",
            short_name="CGUP",
        )

    def test_missing_configuration_leaves_short_name_unset(self) -> None:
        product = ResolvedProductDto.from_included(
            resource("600", "products", name="No Short Name Fund")
        )

        assert product == ResolvedProductDto(id="600", name="No Short Name Fund", short_name=None)


class TestAccountRowResponse:
    def test_passes_through_qualification_object_and_eligibility_enum(self) -> None:
        record = _from_resource(
            _account(
                "1",
                investorQualification={"status": "REG_UNKNOWN", "option": "UNKNOWN"},
                newIssueEligible="ELIGIBLE",
            )
        )
        row = AccountRowResponse.from_record(record)

        assert row.investor_qualification is not None
        assert row.investor_qualification.status == "REG_UNKNOWN"
        assert row.investor_qualification.option == "UNKNOWN"
        assert row.new_issue_eligible == "ELIGIBLE"

    def test_empty_qualification_is_omitted(self) -> None:
        record = _from_resource(_account("1", investorQualification={}))
        row = AccountRowResponse.from_record(record)

        assert row.investor_qualification is None
