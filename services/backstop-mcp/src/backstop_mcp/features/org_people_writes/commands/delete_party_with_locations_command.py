"""Locations-before-party cascade reused by `delete_person` and `delete_organization`."""

import logging
from typing import Literal
from urllib.parse import quote

from fastmcp.exceptions import ToolError

from backstop_mcp.backstop_client import (
    BackstopApiSingleResourceDocument,
    BackstopClient,
    Included,
    IncludedResource,
)
from backstop_mcp.features.org_people_writes.api_responses import (
    ContactLocationAttributes,
    OrganizationWriteAttributes,
    PersonWriteAttributes,
)
from backstop_mcp.features.org_people_writes.commands.modify_contact_location_command import (
    ModifyContactLocationCommand,
)

type PartyCollection = Literal["people", "organizations"]

logger = logging.getLogger(__name__)

_INCLUDE = "contactLocations"
_LOCATION_RESOURCE = IncludedResource[ContactLocationAttributes]
_PEOPLE_DOCUMENT = BackstopApiSingleResourceDocument[PersonWriteAttributes]
_ORGANIZATION_DOCUMENT = BackstopApiSingleResourceDocument[OrganizationWriteAttributes]
_NOUN: dict[PartyCollection, str] = {"people": "person", "organizations": "organization"}


class DeletePartyWithLocationsCommand:
    """GET `include=contactLocations`, delete each location, then DELETE the party."""

    def __init__(
        self,
        *,
        client: BackstopClient,
        modify_contact_location_command: ModifyContactLocationCommand,
    ) -> None:
        self._client: BackstopClient = client
        self._modify_contact_location_command: ModifyContactLocationCommand = (
            modify_contact_location_command
        )

    async def preview(self, *, collection: PartyCollection, party_id: str) -> str:
        document, location_ids = await self._get(collection=collection, party_id=party_id)
        return self._prompt(
            collection=collection,
            party_id=party_id,
            name=document.data.attributes.name,
            location_count=len(location_ids),
        )

    async def run(self, *, collection: PartyCollection, party_id: str) -> tuple[str, ...]:
        _document, location_ids = await self._get(collection=collection, party_id=party_id)
        deleted_location_ids = await self._delete_contact_locations(
            collection=collection,
            party_id=party_id,
            location_ids=location_ids,
        )
        await self._client.delete(f"/{collection}/{quote(party_id, safe='')}")
        logger.warning(
            "org_people_writes.party.deleted",
            extra={
                "id": party_id,
                "collection": collection,
                "deleted_location_ids": deleted_location_ids,
            },
        )
        return deleted_location_ids

    async def _get(
        self, *, collection: PartyCollection, party_id: str
    ) -> tuple[
        BackstopApiSingleResourceDocument[PersonWriteAttributes]
        | BackstopApiSingleResourceDocument[OrganizationWriteAttributes],
        tuple[str, ...],
    ]:
        schema = _PEOPLE_DOCUMENT if collection == "people" else _ORGANIZATION_DOCUMENT
        path = f"/{collection}/{quote(party_id, safe='')}"
        document = await self._client.get(path, schema=schema, params={"include": _INCLUDE})
        return document, self._contact_location_ids(document)

    def _prompt(
        self,
        *,
        collection: PartyCollection,
        party_id: str,
        name: str | None,
        location_count: int,
    ) -> str:
        noun = _NOUN[collection]
        location_word = "location" if location_count == 1 else "locations"
        lines = [
            f"Permanently delete this {noun} from Backstop? There is no recycle bin.",
            (
                f"This also hard-deletes {location_count} contact {location_word}. "
                + "Deleting the party first would leave those addresses undeletable."
            ),
            "",
            f"id: {party_id}",
        ]
        if name:
            lines.append(f"name: {name}")
        lines.append(f"contact locations: {location_count}")
        return "\n".join(lines)

    def _contact_location_ids(
        self,
        document: BackstopApiSingleResourceDocument[PersonWriteAttributes]
        | BackstopApiSingleResourceDocument[OrganizationWriteAttributes],
    ) -> tuple[str, ...]:
        linkage_ids = tuple(
            location_id for location_id in document.data.related_ids(_INCLUDE) if location_id
        )
        if linkage_ids:
            return linkage_ids
        linked = Included(document.included).by_type("contact-locations", schema=_LOCATION_RESOURCE)
        return tuple(item.id for item in linked if item.id)

    async def _delete_contact_locations(
        self,
        *,
        collection: PartyCollection,
        party_id: str,
        location_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        deleted: list[str] = []
        failures: list[str] = []
        for location_id in location_ids:
            assert location_id, "contact-locations id must be non-empty before DELETE"
            try:
                await self._modify_contact_location_command.run(
                    party_id=party_id,
                    location=None,
                    delete_location_id=location_id,
                )
            except ToolError as exc:
                failures.append(f"{location_id}: {exc}")
            else:
                deleted.append(location_id)
        if failures:
            noun = _NOUN[collection]
            removed = ", ".join(deleted) if deleted else "none"
            raise ToolError(
                "Failed to delete contact location(s) "
                + "; ".join(failures)
                + f". The {noun} was not deleted. Already removed location ids: {removed}."
            )
        return tuple(deleted)
