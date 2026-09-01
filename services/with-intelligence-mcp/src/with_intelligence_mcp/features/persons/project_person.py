from with_intelligence_mcp.features.persons.api_responses import (
    PersonExtendedAttributes,
    PersonRoleAttributes,
)
from with_intelligence_mcp.features.persons.responses import PersonResponse


def project_person(record: PersonExtendedAttributes, organisation_id: int) -> PersonResponse:
    """Present the person by the role they hold at `organisation_id`.

    `person_roles` spans every organisation they have worked at, so taking the first would
    attribute someone's previous employer's job title to this investor.
    """
    role = _role_at(record, organisation_id)
    return PersonResponse(
        id=record.id,
        name=record.full_name or record.name,
        job_title=role.job_title if role else None,
        seniority=role.seniority.name if role and role.seniority else None,
        specialism=role.specialisms.name if role and role.specialisms else None,
        email=role.primary_email if role else None,
        phone=(role.primary_phone or role.office_phone) if role else None,
        linkedin=record.linked_in_url,
        biography=record.biography,
        is_main_contact=role.main_for_organisation if role else None,
        is_current=not (role.end_date) if role else True,
        role_started=role.start_date if role else None,
        role_ended=role.end_date if role else None,
    )


def _role_at(record: PersonExtendedAttributes, organisation_id: int) -> PersonRoleAttributes | None:
    """The role at this organisation, preferring a current one over a role they have left."""
    matching = [
        role
        for role in record.person_roles
        if role.organisation is not None
        and organisation_id in (role.organisation.id, role.organisation.org_entity_id)
    ]
    if not matching:
        return None
    current = [role for role in matching if not role.end_date]
    return current[0] if current else matching[0]
