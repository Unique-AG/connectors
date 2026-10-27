"""Create, patch, or delete `contact-locations` rows. `contact.type` is always `contacts`."""

import logging
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

logger = logging.getLogger(__name__)
_Document = BackstopApiSingleResourceDocument[ContactLocationAttributes]
_RESOURCE_TYPE = "contact-locations"
_tracer = trace.get_tracer(__name__)


class ModifyContactLocationCommand:
    """Location writes: delete first, then create or patch each remaining item."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(
        self,
        *,
        party_id: str,
        locations: tuple[ContactLocationInput, ...] = (),
        delete_location_ids: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        with _tracer.start_as_current_span(
            "org_people_writes.command.modify_contact_location",
            record_exception=False,
            set_status_on_exception=False,
        ):
            deleted: list[str] = []
            for delete_location_id in delete_location_ids:
                try:
                    await self._delete(delete_location_id)
                except BackstopApiError as exc:
                    self._log_deleted(party_id, tuple(deleted))
                    self._reraise_write_error(exc, operation="deleted")
                deleted.append(delete_location_id)
            self._log_deleted(party_id, tuple(deleted))
            created: list[str] = []
            updated: list[str] = []
            written: list[str] = []
            for location in locations:
                creating = location.location_id is None
                try:
                    location_id = (
                        await self._create(party_id=party_id, location=location)
                        if creating
                        else await self._update(location=location)
                    )
                except BackstopApiError as exc:
                    self._log_written(party_id, tuple(created), tuple(updated), tuple(written))
                    self._reraise_write_error(exc, operation="created" if creating else "updated")
                if creating:
                    created.append(location_id)
                else:
                    updated.append(location_id)
                written.append(location_id)
            self._log_written(party_id, tuple(created), tuple(updated), tuple(written))
            return tuple(written)

    def _log_deleted(self, party_id: str, deleted_ids: tuple[str, ...]) -> None:
        if not deleted_ids:
            return
        logger.warning(
            "org_people_writes.contact_location.deleted",
            extra={"party_id": party_id, "count": len(deleted_ids), "ids": deleted_ids},
        )

    def _log_written(
        self,
        party_id: str,
        created_ids: tuple[str, ...],
        updated_ids: tuple[str, ...],
        written_ids: tuple[str, ...],
    ) -> None:
        if not written_ids:
            return
        logger.info(
            "org_people_writes.contact_location.written",
            extra={
                "party_id": party_id,
                "created_count": len(created_ids),
                "updated_count": len(updated_ids),
                "ids": written_ids,
            },
        )

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

    def _reraise_write_error(self, exc: BackstopApiError, *, operation: str) -> Never:
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
                + f"{operation}. This is not a missing location."
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
