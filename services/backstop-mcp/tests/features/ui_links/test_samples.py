"""Pinned sample path+query strings. Host is the only substitution."""

import pytest
from pydantic import ValidationError

from backstop_mcp.features.custom_fields import CustomFieldDefinitionResponse
from backstop_mcp.features.ui_links import (
    AccountLinkTargetDto,
    BackstopLinkResponse,
    BackstopLinkTargetDto,
    BuildEntityLinkUtil,
    CallLinkTargetDto,
    DocumentLinkTargetDto,
    EmailLinkTargetDto,
    MeetingLinkTargetDto,
    NoteLinkTargetDto,
    OpportunityLinkTargetDto,
    OrganizationLinkTargetDto,
    ParsedBackstopLinkResponse,
    ParseEntityLinkUtil,
    PersonLinkTargetDto,
    ProductLinkTargetDto,
    TaskLinkTargetDto,
)
from tests.features.ui_links.conftest import UI_BASE, path_and_query

_BUILDER = BuildEntityLinkUtil()
_PARSER = ParseEntityLinkUtil()


def _only_url(target: BackstopLinkTargetDto, tabs: tuple[str, ...] = ()) -> str:
    result = _BUILDER.run(target=target, ui_base_url=UI_BASE, tabs=tabs)
    assert isinstance(result, BackstopLinkResponse)
    assert len(result.links) == 1
    return result.links[0].url


@pytest.mark.parametrize(
    ("target", "sample"),
    [
        (
            CallLinkTargetDto(entity_activity_details_id="76777353"),
            "/backstop/activities.jsp/calls/76777353",
        ),
        (
            MeetingLinkTargetDto(entity_activity_details_id="76777273"),
            "/backstop/activities.jsp/meetings/76777273",
        ),
        (
            NoteLinkTargetDto(entity_activity_details_id="26211573"),
            "/backstop/activities.jsp/notes/26211573",
        ),
        (
            DocumentLinkTargetDto(entity_activity_details_id="128365105"),
            "/backstop/activities.jsp/documents/128365105",
        ),
    ],
)
def test_activity_jsp_samples_match_path_exactly(
    target: BackstopLinkTargetDto, sample: str
) -> None:
    assert path_and_query(_only_url(target)) == sample


def test_email_sample_matches_path_and_query_exactly() -> None:
    url = _only_url(EmailLinkTargetDto(entity_activity_details_id="1804463726"))
    assert path_and_query(url) == (
        "/backstop/crm/collaboration/DisplayEmailMessage.action"
        + "?summaryId=1804463726&showControls=true"
    )


def test_task_sample_matches_path_and_query_exactly() -> None:
    url = _only_url(TaskLinkTargetDto(task_id="2741757"))
    assert path_and_query(url) == (
        "/backstop/crm/Task.action?popupAddEditTask=&taskId=2741757&workflowTaskId=&viewOnly=true"
    )


@pytest.mark.parametrize(
    ("target", "tabs", "sample"),
    [
        (
            OrganizationLinkTargetDto(party_id="341764767"),
            ("summary",),
            "https://tenant.example.test/backstop/crm/ManageOrganization.action"
            "?display=&party_id=341764767&viewType=summary",
        ),
        (
            OrganizationLinkTargetDto(party_id="341764767"),
            ("detail",),
            "https://tenant.example.test/backstop/crm/ManageOrganization.action"
            "?display=&party_id=341764767&viewType=detail",
        ),
        (
            PersonLinkTargetDto(party_id="412345678"),
            ("detail",),
            "https://tenant.example.test/backstop/crm/ManagePerson.action"
            "?display=&party_id=412345678&viewType=detail",
        ),
        (
            ProductLinkTargetDto(entity_id="123456789"),
            (),
            "https://tenant.example.test/backstop/fundaccounting/portfolio/ManageHedgeFund.action"
            "?display=&entityId=123456789",
        ),
        (
            ProductLinkTargetDto(entity_id="123456789"),
            ("accounts",),
            "https://tenant.example.test/backstop/fundaccounting/portfolio/ManageHedgeFund.action"
            "?display=&entityId=123456789&viewType=accounts",
        ),
        (
            AccountLinkTargetDto(entity_id="33578475"),
            ("summary",),
            "https://tenant.example.test/backstop/fundaccounting/ManageAccount.action"
            "?display=&entityId=33578475&acctViewType=summary",
        ),
        (
            OpportunityLinkTargetDto(entity_id="5755163"),
            ("activity",),
            "https://tenant.example.test/backstop/crm/Opportunity.action"
            "?display=&entityId=5755163&viewType=activity",
        ),
    ],
)
def test_standard_entity_samples_match_url_exactly(
    target: BackstopLinkTargetDto, tabs: tuple[str, ...], sample: str
) -> None:
    assert _only_url(target, tabs=tabs) == sample


@pytest.mark.parametrize(
    ("target", "layout_name", "view_entity_type", "sample"),
    [
        (
            OrganizationLinkTargetDto(party_id="341764767"),
            "Investor Information",
            "OrganizationBean",
            "/backstop/crm/ManageOrganization.action?display=&viewEntityType=OrganizationBean"
            + "&entityId=341764767&layoutName=Investor+Information",
        ),
        (
            OrganizationLinkTargetDto(party_id="341764767"),
            "Events",
            "PartyBean",
            "/backstop/crm/ManageOrganization.action?display=&viewEntityType=PartyBean"
            + "&entityId=341764767&layoutName=Events",
        ),
        (
            OpportunityLinkTargetDto(entity_id="5755163"),
            "Master Pipeline",
            "OpportunityBean",
            "/backstop/crm/Opportunity.action?display=&viewEntityType=OpportunityBean"
            + "&entityId=5755163&layoutName=Master+Pipeline",
        ),
    ],
)
def test_layout_samples_match_path_and_query_exactly(
    target: BackstopLinkTargetDto,
    layout_name: str,
    view_entity_type: str,
    sample: str,
) -> None:
    result = _BUILDER.run(
        target=target,
        ui_base_url=UI_BASE,
        tabs=(),
        layout_name=layout_name,
        view_entity_type=view_entity_type,
    )
    assert isinstance(result, BackstopLinkResponse)
    layout_url = result.links[-1].url
    assert path_and_query(layout_url) == sample


def test_layout_link_from_custom_field_definition_response() -> None:
    definition = CustomFieldDefinitionResponse(
        id="1",
        name="Pipeline field",
        entity_type="OpportunityBean",
        layout_name="Master Pipeline",
    )
    assert definition.layout_name is not None
    result = _BUILDER.run(
        target=OpportunityLinkTargetDto(entity_id="5755163"),
        ui_base_url=UI_BASE,
        tabs=(),
        layout_name=definition.layout_name,
        view_entity_type=definition.entity_type,
    )
    assert isinstance(result, BackstopLinkResponse)
    assert (
        path_and_query(result.links[-1].url)
        == "/backstop/crm/Opportunity.action?display=&viewEntityType=OpportunityBean"
        + "&entityId=5755163&layoutName=Master+Pipeline"
    )


def test_landing_sample_parses_resource_type_and_entity_id() -> None:
    url = (
        f"{UI_BASE}/backstop/utility/LandingPageUrl.action"
        + "?resourceType=opportunities&entityId=5755163"
    )
    parsed = _PARSER.run(url=url)
    assert isinstance(parsed, ParsedBackstopLinkResponse)
    assert parsed.resource_type == "opportunities"
    assert parsed.entity_id == "5755163"
    assert parsed.to_target() is None
    assert parsed.suggested_tool == "get_opportunities_by_ids"


def test_email_target_rejects_activity_id() -> None:
    with pytest.raises(ValidationError):
        EmailLinkTargetDto.model_validate({"kind": "email", "activity_id": "1804463726"})

    accepted = EmailLinkTargetDto.model_validate(
        {"kind": "email", "entity_activity_details_id": "1804463726"}
    )
    assert accepted.entity_activity_details_id == "1804463726"
