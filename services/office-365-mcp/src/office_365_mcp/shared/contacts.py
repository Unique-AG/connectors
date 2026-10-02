from typing import Self

from msgraph.generated.models.contact import Contact
from msgraph.generated.models.email_address import EmailAddress
from pydantic import BaseModel, Field

from office_365_mcp.shared.handles import ContactHandle


class ContactEmailAddress(BaseModel):
    name: str | None = Field(
        description=(
            "The name that the contact shows beside this address, such as `Alex Wilber`. The "
            + "value is null when the contact holds no name for this address."
        )
    )
    address: str | None = Field(
        description=(
            "The SMTP address that the contact holds, such as `alexw@example.com`. A contact "
            + "can hold an old address. The value is null when the contact holds no address."
        )
    )

    @classmethod
    def from_email_address(cls, email: EmailAddress) -> Self:
        return cls(name=email.name, address=email.address)


SUMMARY_FIELDS: tuple[str, ...] = (
    "id",
    "displayName",
    "givenName",
    "surname",
    "emailAddresses",
    "businessPhones",
    "homePhones",
    "mobilePhone",
    "companyName",
    "jobTitle",
)


class ContactSummary(BaseModel):
    uri: str = Field(
        description=(
            "The handle of this contact. Pass it as `uri` to outlook_read_contact to read the "
            + "whole contact. Copy the handle word for word. Do not build a handle from a name "
            + "or an id."
        )
    )
    display_name: str | None = Field(
        description=(
            "The name that Outlook shows for the contact, such as `Alex Wilber`. Two contacts "
            + "can have the same name. The value is null when the contact holds no name."
        )
    )
    given_name: str | None = Field(
        description=(
            "The given name, or first name, that the contact holds. The value is null when the "
            + "contact holds no given name."
        )
    )
    surname: str | None = Field(
        description=(
            "The family name, or last name, that the contact holds. The value is null when the "
            + "contact holds no surname."
        )
    )
    email_addresses: list[ContactEmailAddress] = Field(
        description=(
            "Every email address that the contact holds, in the order that Microsoft 365 "
            + "returns them. A contact can hold more than one address. The list is empty when "
            + "the contact holds no address."
        )
    )
    business_phones: list[str] = Field(
        description=(
            "The business telephone numbers that the contact holds, as text. The list is empty "
            + "when the contact holds no business number."
        )
    )
    home_phones: list[str] = Field(
        description=(
            "The home telephone numbers that the contact holds, as text. The list is empty when "
            + "the contact holds no home number."
        )
    )
    mobile_phone: str | None = Field(
        description=(
            "The mobile telephone number that the contact holds, as text. The value is null "
            + "when the contact holds no mobile number."
        )
    )
    company_name: str | None = Field(
        description=(
            "The name of the company that the contact holds for this person. The value is null "
            + "when the contact holds no company."
        )
    )
    job_title: str | None = Field(
        description=(
            "The job title that the contact holds for this person. The value is null when the "
            + "contact holds no job title."
        )
    )

    @classmethod
    def from_contact(cls, contact: Contact) -> Self:
        assert contact.id is not None, "Graph answered a contact with no id"
        return cls(
            uri=ContactHandle(contact.id).uri,
            display_name=contact.display_name,
            given_name=contact.given_name,
            surname=contact.surname,
            email_addresses=[
                ContactEmailAddress.from_email_address(email)
                for email in contact.email_addresses or []
            ],
            business_phones=list(contact.business_phones or []),
            home_phones=list(contact.home_phones or []),
            mobile_phone=contact.mobile_phone,
            company_name=contact.company_name,
            job_title=contact.job_title,
        )
