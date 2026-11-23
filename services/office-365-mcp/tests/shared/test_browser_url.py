import pytest
from pydantic import BaseModel, TypeAdapter

from office_365_mcp.shared.files import DriveItemSummary, browser_url
from office_365_mcp.shared.sharepoint.lists import ListItemSummary
from office_365_mcp.tools.sharepoint_copy_item import CopyStarted
from office_365_mcp.tools.sharepoint_invite import Invitation
from office_365_mcp.tools.sharepoint_list_drives import DriveSummary
from office_365_mcp.tools.sharepoint_list_lists import ListSummary

_SITE = "https://contoso.sharepoint.invalid/sites/Sales/Shared%20Documents/"


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ("Q1 plan [v2].docx", "Q1%20plan%20%5Bv2%5D.docx"),
        ("Q1%20plan.docx", "Q1%20plan.docx"),
        ("50% plan.docx", "50%25%20plan.docx"),
        ("100%.docx", "100%25.docx"),
        ("Q1;Q2 (draft.docx", "Q1%3BQ2%20%28draft.docx"),
        ("Bericht (final).docx", "Bericht%20%28final%29.docx"),
        ("Übersicht.docx", "%C3%9Cbersicht.docx"),
    ],
    ids=repr,
)
def test_a_link_opens_in_a_browser_and_survives_markdown(raw: str, escaped: str) -> None:
    assert browser_url(_SITE + raw) == _SITE + escaped


def test_escaping_a_link_twice_changes_nothing() -> None:
    once = browser_url(_SITE + "50% plan (v1).docx")

    assert browser_url(once) == once


def _named(value: object) -> str:
    return value.__name__ if isinstance(value, type) else str(value)


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (DriveItemSummary, "web_url"),
        (ListItemSummary, "web_url"),
        (CopyStarted, "source_web_url"),
        (CopyStarted, "destination_web_url"),
        (Invitation, "web_url"),
        (DriveSummary, "web_url"),
        (ListSummary, "web_url"),
    ],
    ids=_named,
)
def test_every_sharepoint_link_a_tool_returns_is_escaped(
    model: type[BaseModel], field: str
) -> None:
    annotation = model.model_fields[field].annotation
    assert annotation is not None

    assert TypeAdapter(annotation).validate_python(_SITE + "Q1 plan.docx") == (
        _SITE + "Q1%20plan.docx"
    )
