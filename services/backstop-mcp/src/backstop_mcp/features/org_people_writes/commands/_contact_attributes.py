"""Person/organization write payload helpers.

Python-name → wire-key mapping for contact attributes and relationships. JSON:API
envelopes (`json_api_update`, `relationship_data`, …) live on `backstop_client`.
"""

from backstop_mcp.backstop_client import isoformat, relationship_data, relationship_to_one
from backstop_mcp.features.org_people_writes.update_organization_input import (
    UpdateOrganizationInput,
)
from backstop_mcp.features.org_people_writes.update_person_input import UpdatePersonInput

__all__ = [
    "organization_attributes",
    "organization_relationships",
    "person_attributes",
    "person_relationships",
]


def person_attributes(person: UpdatePersonInput) -> dict[str, object | None]:
    """Wire attributes for a person write. Callers wrap with `omit_none_values`."""
    return {
        "firstName": person.first_name,
        "middleName": person.middle_name,
        "lastName": person.last_name,
        "nickName": person.nick_name,
        "prefix": person.prefix,
        "suffix": person.suffix,
        "salutation": person.salutation,
        "pronunciation": person.pronunciation,
        "gender": person.gender,
        "birthday": isoformat(person.birthday),
        "spouseName": person.spouse_name,
        "jobTitle": person.job_title,
        "department": person.department,
        "companyName": person.company_name,
        "contactDescription": person.contact_description,
        "email": person.email,
        "email2": person.email2,
        "email3": person.email3,
        "mobilePhone": person.mobile_phone,
        "website": person.website,
        "otherId": person.other_id,
        "investableAssets": person.investable_assets,
        "isEmployee": person.is_employee,
    }


def person_relationships(
    person: UpdatePersonInput, *, owner: dict[str, object] | None, omit_empty: bool = False
) -> dict[str, object | None]:
    """Wire relationships for a person write.

    `owner` is the pre-resolved `representative` payload. Creates pass
    `omit_empty=True` so `()` is not sent; updates leave `()` as a clear.
    Callers wrap with `omit_none_values`.
    """
    return {
        "company": relationship_to_one("organizations", person.company_id),
        "contactSource": relationship_to_one("contact-sources", person.contact_source_id),
        "referralSource": relationship_to_one("contacts", person.referral_source_id),
        "representative": owner,
        "categories": relationship_data(
            "contact-categories", _to_many_ids(person.add_category_ids, omit_empty=omit_empty)
        ),
    }


def organization_attributes(
    new_organization_fields: UpdateOrganizationInput,
) -> dict[str, object | None]:
    """Wire attributes for an organization write. Callers wrap with `omit_none_values`."""
    return {
        "name": new_organization_fields.name,
        "legalName": new_organization_fields.legal_name,
        "aliases": new_organization_fields.aliases,
        "contactDescription": new_organization_fields.contact_description,
        "dateFounded": isoformat(new_organization_fields.date_founded),
        "email": new_organization_fields.email,
        "email2": new_organization_fields.email2,
        "email3": new_organization_fields.email3,
        "website": new_organization_fields.website,
        "otherId": new_organization_fields.other_id,
        "investableAssets": new_organization_fields.investable_assets,
        "numberOfEmployees": new_organization_fields.number_of_employees,
        "internalOrganization": new_organization_fields.internal_organization,
        "ria": new_organization_fields.ria,
        "matchingDomains": (
            list(new_organization_fields.matching_domains)
            if new_organization_fields.matching_domains is not None
            else None
        ),
    }


def organization_relationships(
    new_organization_fields: UpdateOrganizationInput,
    *,
    owner: dict[str, object] | None,
    omit_empty: bool = False,
) -> dict[str, object | None]:
    """Wire relationships for an organization write.

    `owner` is the pre-resolved `representative` payload. Creates pass
    `omit_empty=True` so `()` is not sent; updates leave `()` as a clear.
    Callers wrap with `omit_none_values`.
    """
    return {
        "contactSource": relationship_to_one(
            "contact-sources", new_organization_fields.contact_source_id
        ),
        "referralSource": relationship_to_one(
            "contacts", new_organization_fields.referral_source_id
        ),
        "representative": owner,
        "primaryContact": relationship_to_one("people", new_organization_fields.primary_contact_id),
        "categories": relationship_data(
            "contact-categories",
            _to_many_ids(new_organization_fields.add_category_ids, omit_empty=omit_empty),
        ),
    }


def _to_many_ids(ids: tuple[str, ...] | None, *, omit_empty: bool) -> tuple[str, ...] | None:
    if omit_empty:
        return ids or None
    return ids
