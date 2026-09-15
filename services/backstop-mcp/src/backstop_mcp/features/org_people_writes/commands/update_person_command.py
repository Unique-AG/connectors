"""PATCH `/people/{id}`, then optional `/contact-locations` writes."""

import logging
from urllib.parse import quote

from opentelemetry import trace

from backstop_mcp.backstop_client import (
    BackstopApiSingleResourceDocument,
    BackstopClient,
    isoformat,
    json_api_update,
    omit_none_values,
    relationship_data,
    relationship_to_one,
)
from backstop_mcp.features.org_people_writes.api_responses import PersonWriteAttributes
from backstop_mcp.features.org_people_writes.commands.modify_contact_location_command import (
    ModifyContactLocationCommand,
)
from backstop_mcp.features.org_people_writes.responses import UpdatedPersonResponse
from backstop_mcp.features.org_people_writes.update_person_input import UpdatePersonInput
from backstop_mcp.features.system_users import SystemUsersService

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

_Document = BackstopApiSingleResourceDocument[PersonWriteAttributes]
_RESOURCE_TYPE = "people"


class UpdatePersonCommand:
    """Update one person via `PATCH /people/{id}`, then apply location writes."""

    def __init__(
        self,
        *,
        client: BackstopClient,
        system_users_service: SystemUsersService,
        modify_contact_location_command: ModifyContactLocationCommand,
    ) -> None:
        self._client: BackstopClient = client
        self._system_users_service: SystemUsersService = system_users_service
        self._modify_contact_location_command: ModifyContactLocationCommand = (
            modify_contact_location_command
        )

    async def run(self, *, person: UpdatePersonInput, party_id: str) -> UpdatedPersonResponse:
        with _tracer.start_as_current_span("org_people_writes.command.update_person") as span:
            span.set_attribute("party_id", party_id)
            owner = await self._system_users_service.resolve_relationship(person.owner_login)
            await self._patch(person, party_id=party_id, owner=owner)
            location_id = await self._modify_contact_location_command.run(
                party_id=party_id,
                location=person.location,
                delete_location_id=person.delete_location_id,
            )
            written = await self._read(party_id)
            logger.info(
                "org_people_writes.person.updated",
                extra={"id": party_id, "location_id": location_id},
            )
            return UpdatedPersonResponse(
                id=party_id,
                resource_type=_RESOURCE_TYPE,
                mobile_phone=written.data.attributes.mobile_phone,
                location_id=location_id,
            )

    async def _read(self, party_id: str) -> _Document:
        path = f"/{_RESOURCE_TYPE}/{quote(party_id, safe='')}"
        return await self._client.get(path, schema=_Document)

    async def _patch(
        self,
        person: UpdatePersonInput,
        *,
        party_id: str,
        owner: dict[str, object] | None,
    ) -> None:
        attributes = omit_none_values(
            {
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
        )
        relationships = omit_none_values(
            {
                "company": relationship_to_one("organizations", person.company_id),
                "contactSource": relationship_to_one("contact-sources", person.contact_source_id),
                "referralSource": relationship_to_one("contacts", person.referral_source_id),
                "representative": owner,
                "categories": relationship_data("contact-categories", person.add_category_ids),
            }
        )
        # A to-many PATCH appends; `data: []` is the only clear. The replacement ids
        # cannot go on this first PATCH — they would be added to the existing list.
        # Clear here, then a second PATCH appends the new members when the list is
        # non-empty.
        if person.replace_category_ids is not None:
            relationships["categories"] = relationship_data("contact-categories", ())
        if not attributes and not relationships:
            return
        path = f"/{_RESOURCE_TYPE}/{quote(party_id, safe='')}"
        await self._client.patch(
            path,
            schema=_Document,
            json=json_api_update(
                resource_type=_RESOURCE_TYPE,
                resource_id=party_id,
                attributes=attributes,
                relationships=relationships or None,
            ),
        )
        # Replacement members cannot go on the first PATCH: a to-many write
        # appends, so they would sit on top of the uncleared list. This request
        # runs only after `data: []` has cleared `categories`.
        if person.replace_category_ids:
            await self._client.patch(
                path,
                schema=_Document,
                json=json_api_update(
                    resource_type=_RESOURCE_TYPE,
                    resource_id=party_id,
                    attributes={},
                    relationships={
                        "categories": relationship_data(
                            "contact-categories", person.replace_category_ids
                        )
                    },
                ),
            )
