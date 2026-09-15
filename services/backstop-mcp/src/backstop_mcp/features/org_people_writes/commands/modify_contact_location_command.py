"""Create, patch, or delete a `contact-locations` row. `contact.type` is always `contacts`."""

from typing import Never
from urllib.parse import quote

from fastmcp.exceptions import ToolError
from opentelemetry import trace

from backstop_mcp.backstop_client import (
    BackstopApiError,
    BackstopApiSingleResourceDocument,
    BackstopClient,
    json_api_create,
    json_api_update,
    omit_none_values,
    relationship_to_one,
)
from backstop_mcp.features.org_people_writes.api_responses import ContactLocationAttributes
from backstop_mcp.features.org_people_writes.contact_location_input import ContactLocationInput

_Document = BackstopApiSingleResourceDocument[ContactLocationAttributes]
_RESOURCE_TYPE = "contact-locations"
_tracer = trace.get_tracer(__name__)


class ModifyContactLocationCommand:
    """One location write: create when `location_id` is missing, else patch, else delete."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(
        self,
        *,
        party_id: str,
        location: ContactLocationInput | None,
        delete_location_id: str | None,
    ) -> str | None:
        with _tracer.start_as_current_span("org_people_writes.command.modify_contact_location"):
            location_id: str | None = None
            try:
                if location is not None and location.location_id is None:
                    location_id = await self._create(party_id=party_id, location=location)
                elif location is not None:
                    location_id = await self._update(location=location)
                if delete_location_id is not None:
                    await self._delete(delete_location_id)
            except BackstopApiError as exc:
                self._reraise_write_error(exc)
            return location_id

    async def _create(self, *, party_id: str, location: ContactLocationInput) -> str:
        created = await self._client.post(
            f"/{_RESOURCE_TYPE}",
            schema=_Document,
            json=json_api_create(
                resource_type=_RESOURCE_TYPE,
                attributes=self._location_attributes(location),
                relationships={"contact": relationship_to_one("contacts", party_id)},
            ),
        )
        return created.data.id

    async def _update(self, *, location: ContactLocationInput) -> str:
        assert location.location_id is not None
        path = f"/{_RESOURCE_TYPE}/{quote(location.location_id, safe='')}"
        await self._client.patch(
            path,
            schema=_Document,
            json=json_api_update(
                resource_type=_RESOURCE_TYPE,
                resource_id=location.location_id,
                attributes=self._location_attributes(location),
            ),
        )
        return location.location_id

    async def _delete(self, location_id: str) -> None:
        await self._client.delete(f"/{_RESOURCE_TYPE}/{quote(location_id, safe='')}")

    def _reraise_write_error(self, exc: BackstopApiError) -> Never:
        detail = exc.detail.casefold()
        code = (exc.code or "").casefold()
        if "location names for a party must be unique" in detail:
            raise ToolError(
                "Location title is already used on this party. Location names for a party "
                + "must be unique."
            ) from exc
        if exc.status_code == 404 and "partynotfound" in f"{code} {detail}":
            raise ToolError(
                "The parent party for this location is gone, so the location cannot be "
                + "deleted. This is not a missing location."
            ) from exc
        raise exc

    def _location_attributes(self, location: ContactLocationInput) -> dict[str, object]:
        return omit_none_values(
            {
                "locationTitle": location.location_title,
                "address": location.address,
                "city": location.city,
                "state": location.state,
                "country": location.country,
                "postalCode": location.postal_code,
                "phoneNumber": location.phone_number,
                "secondaryPhoneNumber": location.secondary_phone_number,
                "fax": location.fax,
                "note": location.note,
                "isPrimaryLocation": location.is_primary_location,
            }
        )
