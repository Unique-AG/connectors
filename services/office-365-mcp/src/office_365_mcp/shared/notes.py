from datetime import datetime
from typing import Protocol, Self

from msgraph.generated.models.external_link import ExternalLink
from msgraph.generated.models.onenote_page import OnenotePage
from pydantic import BaseModel, Field

from office_365_mcp.shared.handles import OnenotePageHandle, OnenoteSectionHandle

PAGE_FIELDS: tuple[str, ...] = ("id", "title", "createdDateTime", "lastModifiedDateTime", "links")
PAGE_EXPANSIONS: tuple[str, ...] = ("parentSection", "parentNotebook")


class _Links(Protocol):
    @property
    def one_note_web_url(self) -> ExternalLink | None: ...

    @property
    def one_note_client_url(self) -> ExternalLink | None: ...


def web_url_of(links: _Links | None) -> str | None:
    if links is None or links.one_note_web_url is None:
        return None
    return links.one_note_web_url.href


def client_url_of(links: _Links | None) -> str | None:
    if links is None or links.one_note_client_url is None:
        return None
    return links.one_note_client_url.href


class PageSummary(BaseModel):
    uri: str = Field(
        description=(
            "This page's handle: onenote:///pages/{id}, with the id percent-encoded. Pass it "
            + "verbatim to onenote_read_page to read the page or to onenote_append_to_page to "
            + "add to it. Never build one: a page id alone reaches nothing."
        )
    )
    title: str | None = Field(
        description=(
            "The page title as Microsoft's page index holds it. Null when the page has none. "
            + "That index lags a create or an edit by minutes, sometimes many, so a page written "
            + "recently can come back with an empty title here while its HTML, from "
            + "onenote_read_page, already carries the right one."
        )
    )
    created_at: datetime | None = Field(
        description=(
            "When the page was created, as Graph reported it. Null when Graph recorded none."
        )
    )
    last_modified_at: datetime | None = Field(
        description=(
            "When the page last changed, as Graph reported it. Null when Graph recorded none. A "
            + "listing of pages orders by this field, newest change first. Microsoft's page "
            + "index lags an edit by minutes, so a page written moments ago can still show the "
            + "earlier value here."
        )
    )
    web_url: str | None = Field(
        description=(
            "The address that opens this page in OneNote on the web, for a person to follow. "
            + "This connector cannot read a page from it."
        )
    )
    client_url: str | None = Field(
        description=(
            "The address that opens this page in the OneNote desktop app, if the person has it "
            + "installed."
        )
    )
    section_uri: str | None = Field(
        description=(
            "The handle of the section holding this page: onenote:///sections/{id}. Pass it to "
            + "onenote_list_pages to see this page's siblings, or to onenote_create_page to add "
            + "a page beside it. Null when Graph named no parent section for this page."
        )
    )
    section_name: str | None = Field(
        description=(
            "The display name of the section holding this page. Null when Graph gave no parent "
            + "section."
        )
    )
    notebook_name: str | None = Field(
        description=(
            "The display name of the notebook holding this page. Null when Graph gave no parent "
            + "notebook."
        )
    )

    @classmethod
    def from_page(cls, page: OnenotePage) -> Self | None:
        if page.id is None:
            return None
        section = page.parent_section
        section_id = section.id if section is not None else None
        notebook = page.parent_notebook
        return cls(
            uri=OnenotePageHandle(page.id).uri,
            title=page.title,
            created_at=page.created_date_time,
            last_modified_at=page.last_modified_date_time,
            web_url=web_url_of(page.links),
            client_url=client_url_of(page.links),
            section_uri=None if section_id is None else OnenoteSectionHandle(section_id).uri,
            section_name=section.display_name if section is not None else None,
            notebook_name=notebook.display_name if notebook is not None else None,
        )
